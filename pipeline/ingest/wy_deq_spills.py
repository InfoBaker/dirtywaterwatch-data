"""Wyoming DEQ public spill list, the sewage rows -> data/build/events/wy-deq-spill-list.json

Source
  Wyoming Department of Environmental Quality (DEQ), Spills and Complaints system: the public spill list behind the
  "Download Report" button of https://deqspills.wyo.gov/ (its other screens need a login),
  GET https://deqspills-api.wyo.gov/PublicReport/GetIncidentPublicReport (text/csv, no key, no cookie, no licence
  statement; saved by the page as "Spill-List_YYYYMMDD.csv"). Credit "Wyoming Department of Environmental Quality,
  public spill list". Law: WDEQ's WYPDES Sanitary Sewer Overflows page asks a sewer owner or operator to report an
  overflow verbally within 24 hours and in writing within five days; DEQ's spill line takes reports of spills of every
  kind. The list is every spill report DEQ has closed, of every substance; most sewer overflow reports are not on it.

What the list holds (read 2026-11-16, 3,614,703 bytes, 46 s from a Mac)
  6,066 rows of 33 columns (one row wholly blank), incidents from 1970 (a mistyped year) and 1986 to 2026-11-03. Every
  spill row is CurrentStatus "Complete"; "Valid" (61) and "Invalid" (20) occur only on the 81 rows of Substance
  "Harmful Cyanobacterial Bloom" (public bloom reports, IncidentCode "B-...": not read into this feed). The columns
  SpillCouldReachWater and SpillReachedWater hold the same answer on every row (the export repeats one answer, Yes,
  No or Unknown): it is kept as the list's "reached water" answer, under its own name. IncidentCode is not unique (66
  codes on 139 rows).

What is kept (privacy: the repository is public)
  KEPT only. Never saved, logged or printed (WITHHELD): CompanyName (the responsible party: often a person or a
  company), StreetAddress1 and City (the party's mailing address), IncidentAddress (the spill's street address, often a
  home), LocationDescription and AdditionalInfo (narratives with names, telephones, e-mails and addresses), CauseOther
  (the filer's own words for the cause), and the land survey columns (Meridian to QuarterQuarter: a 40-acre square,
  as precise as a point). Three of them are read in memory only, never kept: AdditionalInfo and CauseOther for the
  sewage rule's second test and the point rule's public-works and home words, CompanyName for the operator tie (an
  exact public-system name). SubstanceOther (the substance as filed) and WaterAffected (the water as filed) are kept
  after mi_egle_mienviro.free_text and the person cues ("Mr. <name>", "<given> <surname> reported"), a value that is
  only a person's name removed; WaterAffected is kept only as a water's name (an answer such as "No", "N/A" or "The
  spill did not reach ..." is not a water, and a long account is withheld). IncidentCity is a public place name.
  common.event strips personal keys and build.redact runs over the records last. The raw save holds only the kept,
  scrubbed fields of the sewage rows.

Which rows are sewage (rules only, no model; WHICH_ROWS in the docstring order)
  1. Substance "Harmful Cyanobacterial Bloom" -> counted (meta.bloom_rows), never a record here.
  2. Substances that are not sewage by the list's own category (Produced Water, Crude Oil, Diesel, Oil, Gasoline,
     Condensate, Radioactive Material, Vapor) -> not read.
  3. Substance "Other" or "Hazardous Substance" with SubstanceOther naming sewage (SEWAGE_WORDS: sewage, sewer,
     sanitary, septage, septic, black water, gray water, human waste, a portable toilet, wastewater) is sewage, except:
     - an industrial, oily, fuel or chemical word with no word that names sewage itself (SEWAGE_ITSELF: sewage,
       septic, septage, black water, human waste, a toilet; "untreated", "domestic" and "sanitary" are not enough:
       "Untreated refinery wastewater", "Diesel in sanitary sewer") -> left out "industrial, oily or chemical wastewater" ("Oily Water sewer",
       "Refinery Waste Water", "Brewery wastewater", "Chemical car wash waste water", "F037 sewer sludge");
     - treated wastewater or effluent, with no strong word -> left out "treated wastewater" (owner's scope rule of
       2026-11-04: treated effluent is counted, not shown);
     - a report of an odour (the substance begins with odour, smell or stench) -> left out "odour report";
     - "wastewater" or "effluent" alone (no other sewage word) is sewage only when the cause or the description names a
       sewer works (SEWER_CUES: manhole, sewer main or line, lift or pump station, lagoon, treatment plant, sanitary
       sewer, septic) and no industrial word; otherwise left out "wastewater not shown to be sewage".
  4. Substance "Other" or "Hazardous Substance" with no substance text (blank, "Other", "Unknown"): sewage when the
     description or the cause says sewage (DESC_SEWAGE: raw or untreated sewage, sewage, a sanitary sewer overflow,
     septage) not negated ("no sewage"), and names no industrial, oily or chemical substance.
  The rule errs toward showing a row whose own words say sewage: "sewage sludge" (Park County, 2019, reached the
  Yellowstone River) is a record. raw._sewage_basis says which test took the row.

Record rules
  - Key: IncidentCode, the county ("-nocounty" when none) and a six-character hash of ClosureDate, DEQ's closing
    stamp to the second ("<code>-<county>-<hash>"), the same whichever rows are read with it: two incidents of one code in two counties
    are two records. Two rows sharing a whole key in one read (none on 2026-11-16) are not told apart: the earlier
    record is kept as it was and the read is unhealthy (meta.unread) until DEQ's list tells them apart.
    SubstanceOther is kept word for word only when every word is a substance word (SUBSTANCE_WORDS), else as a label
    of its sewage words; WaterAffected only when each run of capitalised words is a water's name. source_url is the list's address (the list has no page per incident).
  - Times: IncidentDate (YYYY-MM-DD HH:MM:SS, no zone) is the incident's date and time as filed with DEQ, read in
    Mountain time (America/Denver; all of Wyoming keeps it). 00:00:00 is the list's form of a date entered without a
    time (914 of 6,065 rows): the start is that day (time_precision day). The list gives no report or receipt time and
    no end: reported_at, published_at and ended_at are null and status is "unknown", so the status build applies its
    normal rule for a report with no end (the site's caution from the start, then "end not confirmed" to day 30).
    ClosureDate is DEQ's closing of the report (raw.closure_date), never the spill's end. A start more than a day after
    the read is not used (raw._start_not_used).
  - Type: sso, raw._type_basis the substance as filed; a septic tank, a portable toilet or a private line is not a
    public sewer, and the basis says so.
  - Reached water, the list's answer (raw.reached_water_answer): Yes -> raw.reached_water true, placed by the water it
    names or by its own point (raw._placement "own_place_only"; never by an operator's outfall); Unknown or blank ->
    raw.reached_water null, placed only on the water it names (named_water_only; err on safety: a named water counts);
    No -> raw.reached_water false, no water text, placed on no water and listed. A No whose water text itself begins
    "Yes" keeps the text (raw.reached_water "text": the site's caution only, as on Florida's notices).
  - Place: the county (raw.county) and IncidentCity (raw.place). A point (Latitude, Longitude) is used only when it lies
    in Wyoming and in the county the row gives, has three decimals or more, the report names public sewer works or a
    tied operator (POINT_PUBLIC) and nothing that reads as a home or private property (HOME_WORDS); it is rounded to
    three decimals (coord_precision_m 100). Any other point is not kept (raw._point_withheld says why).
  - Operator: CompanyName (in memory) equal to exactly one Wyoming row of data/dischargers.json ("City of Casper",
    after the list's suffixes such as "Wastewater collections"), on a report naming public sewer works and no home ->
    discharger_id and discharger_name; otherwise no operator is named (raw._discharger_basis).
  - Volume: SubstanceQuantity in gallons when SubstanceUnit is Gallons (0 is not a volume); volume_text the quantity
    and unit as given (UnitOther when the unit is Other).
  - Copies: two rows identical in every column (compared in memory, the withheld ones included) but IncidentCode and
    ClosureDate, with an incident time to the minute and a quantity, closed by DEQ within five minutes of each other,
    are one report filed twice: the first code stands, the other is duplicate_of it (raw._duplicate_basis), recomputed
    at every read; a record kept from an earlier read keeps its mark.

Reading and failure
  Every run reads the whole file in one ordinary request (TIMEOUT; no retry loop). A failed request, an answer that is
  not CSV, a header that differs from HEADER, a row with another number of fields, a file that does not end with a line
  break or ends inside a quoted field, more than MAX_BLANK blank rows, a row with fields but no
  IncidentCode, or a read more than MAX_DROP rows (or, for a list under 500 rows, MAX_DROP_SHARE of it) shorter than
  the last complete read is a failed read: ok false, nothing saved, every record kept as it was, exit 1.
  A sewage row whose IncidentDate cannot be read, or that shares its whole key with another row, keeps its earlier record as it was; health false (meta.unread) and
  exit 1 until it reads. A record missing from a complete read stays as a past report (raw._missing_from_list_since).

Cadence and history
  The list is 3.6 MB and slow to answer, and its sewage rows arrive 12 to 18 a year (2025: 18; 2026 to November: 12)
  once DEQ closes them (a median of 18 days after the incident), so a run reads it at most once in EVERY_HOURS (the last successful read in the events file;
  `--force` reads now). The whole history is read every time; `--backfill` reads now and records meta.backfill (rows,
  range, seconds): one request, about 3.6 MB, under two minutes.

Run from pipeline/:  python -m ingest.wy_deq_spills [--file saved.csv] [--backfill] [--force]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, NAME_REMOVED, ROOT, event, now_iso, path_notes_to_meta,
                    read_json, save_raw, scrub_text, write_events, write_json)
from ingest import mi_egle_mienviro as mi

SOURCE_ID = "wy-deq-spill-list"
REGISTRY_IDS = ["wy-deq-spills-portal"]
URL = "https://deqspills-api.wyo.gov/PublicReport/GetIncidentPublicReport"
PAGE_URL = "https://deqspills.wyo.gov/"
STATE_FILE = BUILD_DIR / "wy-deq-spill-list-state.json"
AUTHORITY = "Wyoming DEQ (public spill list)"
CREDIT = "Wyoming Department of Environmental Quality, public spill list"
MOUNTAIN = ZoneInfo("America/Denver")
TIMEOUT = (30, 300)
EVERY_HOURS = 20
MAX_DROP = 5                    # a read more than this many rows shorter than the last complete read is cut short, or
MAX_DROP_SHARE = 0.01           # more than this share of it (at least one row) when that is fewer
MAX_BLANK = 5                   # blank rows: one on 2026-11-16
HEADER = ["IncidentCode", "CompanyName", "StreetAddress1", "City", "IncidentAddress", "IncidentCity", "IncidentDate",
          "SpillSource", "CauseDescription", "CauseOther", "Substance", "SubstanceOther", "SubstanceQuantity",
          "SubstanceUnit", "UnitOther", "Media", "SpillCouldReachWater", "SpillReachedWater", "WaterAffected",
          "AcceptedDivisions", "CurrentStatus", "ClosureDate", "AdditionalInfo", "County", "LocationDescription",
          "Meridian", "Township", "Range", "Section", "Quarter", "QuarterQuarter", "Latitude", "Longitude"]
KEPT = ("IncidentCode", "IncidentCity", "IncidentDate", "SpillSource", "CauseDescription", "Substance",
        "SubstanceOther", "SubstanceQuantity", "SubstanceUnit", "UnitOther", "Media", "SpillReachedWater",
        "WaterAffected", "AcceptedDivisions", "CurrentStatus", "ClosureDate", "County", "Latitude", "Longitude")
WITHHELD = ("CompanyName", "StreetAddress1", "City", "IncidentAddress", "CauseOther", "AdditionalInfo",
            "LocationDescription", "Meridian", "Township", "Range", "Section", "Quarter", "QuarterQuarter")
assert set(KEPT) | set(WITHHELD) | {"SpillCouldReachWater"} == set(HEADER)
WITHHELD_NOTE = ("The list's responsible party, addresses, description, cause in the filer's words and survey "
                 "location are not reproduced here: they can name people and homes. The source record has them.")
WY_BOX = (-111.06, 40.99, -104.05, 45.01)      # west, south, east, north
POINT_DECIMALS = 3

BLOOM = "Harmful Cyanobacterial Bloom"
NOT_SEWAGE_SUBSTANCES = {"Produced Water", "Crude Oil", "Diesel", "Oil", "Gasoline", "Condensate",
                         "Radioactive Material", "Vapor"}
SEWAGE_WORDS = re.compile(r"sewage|sewer|sanitary|septage|septic|black ?water|gr[ae]y ?water|human waste|"
                          r"port[a-]?(?:a[- ]?)?(?:potty|john)|portable toilet|waste ?w[a-z]{3,5}\b|effluent", re.I)
STRONG = re.compile(r"sewage|sanitary|septage|septic|black ?water|human waste|port[a-]?(?:a[- ]?)?(?:potty|john)|"
                    r"portable toilet|raw waste ?water|untreated|domestic", re.I)
# the words that name sewage itself; only these stand against an industrial, oily or fuel word in the same text
# ("Untreated refinery wastewater" and "Diesel in sanitary sewer" are not sewage: Astra review 2026-11-16 P1-4)
SEWAGE_ITSELF = re.compile(r"sewage|septage|septic|black ?water|human waste|port[a-]?(?:a[- ]?)?(?:potty|john)|"
                           r"portable toilet", re.I)
GENERIC_ONLY = re.compile(r"waste ?w[a-z]{3,5}\b|effluent", re.I)
INDUSTRIAL = re.compile(r"\boil|refiner|benzene|brewery|car ?wash|metal|cooling|process|plant waste|pipeline|"
                        r"condensate|nitrate|\bf0?37\b|\bfo37\b|sludge tank|de-? ?icer|chemical|hydrocarbon|"
                        r"produced water|\bfrac\b|amalgam|sump|truck|wash(?:ing|ed)? |fuel|diesel|gasoline|crude", re.I)
# in a cause or description (read in memory), only words that name another substance or an industrial source
INDUSTRIAL_DESC = re.compile(r"\boil(?:y|field)?\b|refiner|hydrocarbon|benzene|process water|produced water|chemical|"
                             r"\bfuel|diesel|gasoline|crude|condensate|truck wash|car ?wash|washing of (?:equipment|vehicles|trucks)|"
                             r"cooling tower|power plant|\bmine\b|mining|frac(?:k|king)? (?:water|fluid)|amalgam|"
                             r"pesticide|glycol|naphtha|acid\b", re.I)
TREATED = re.compile(r"(?<!un)(?<!partially )(?<!partly )\btreated (?:waste ?water|effluent)", re.I)
ODOUR = re.compile(r"^\W*(?:un)?(?:odou?rs?|smells?|stench)\b", re.I)     # the report is of an odour (Astra P1-5)
SEWER_CUES = re.compile(r"manhole|man hole|sewer (?:main|line|backup|system|service|lateral|pipe|division)|city sewer|main line|mainline|lift station|"
                        r"pump station|lagoon|treatment (?:plant|facility|works)|wwtp|wwtf|headworks|"
                        r"sanitary sewer|force main|septic|sewage|collection system", re.I)
DESC_SEWAGE = re.compile(r"(?:raw |untreated )?sewage|sanitary sewer overflow|\bsso\b|septage", re.I)
NEGATED = re.compile(r"\b(?:no|not|non|isn't|wasn't|without)\s+(?:\w+\s+){0,3}$", re.I)
PUBLIC_WORKS = re.compile(r"manhole|man hole|sewer main|main line|mainline|lift station|pump station|lagoon|"
                          r"treatment (?:plant|facility|works)|wwtp|wwtf|headworks|force main|interceptor|"
                          r"collection system|(?:city|town|municipal) sewer|sanitary sewer overflow", re.I)
HOME_WORDS = re.compile(r"\bhouse|\bhome|residen|crawl ?space|basement|\byard\b|trailer|mobile home|\blot\b|"
                        r"apartment|tenant|septic (?:tank|system)|private|property owner|\bcabin|\bcamper|\brv\b|"
                        r"driveway|garage|neighbou?r", re.I)
PLACEHOLDER_SUBSTANCE = re.compile(r"^\s*(?:|other|unknown|unk|n/?a|none|-+|\?)\s*$", re.I)
NO_WATER_TEXT = re.compile(r"^\s*(?:no\b|n/?a\b|na\b|none|nothing|unknown|unk\b|not\b|did not|didn't|the spill did not|"
                           r"there (?:was|were) no|if uncorrected|potential|0\s*$|-+\s*$)", re.I)
YES_PREFIX = re.compile(r"^\s*yes\b[\s,.:;-]*", re.I)
WATER_TEXT_MAX = 100
# "Unnamed Ephemeral Tributary of the Laramie River", "Unnamed drainage to Little Goose Creek": a different water from
# the one named (the convention of ingest/nh_vt_waters.py and ar_transforms.py), so the named water is not used
TRIBUTARY_OF = re.compile(r"\b(?:trib(?:utary|\.)?|drainage|draw|ditch|swale|gulch)\s+(?:of|to|into)\b", re.I)
NOT_REACHED = re.compile(r"did not|didn't|does not|not reach|never reached|no (?:water|body|surface)|absorbed|soaked|"
                         r"contained|remained", re.I)
UTILITY_SUFFIX = re.compile(r"(?:\s+(?:wastewater|waste water|wasterwater|sewer|collections?|utilities|public works|"
                            r"division|department|dept|wwtp|treatment plant|-))+\s*$", re.I)


# ---------------------------------------------------------------- helpers

# SubstanceOther is kept word for word only when every word is one of these (the words of the sewage substances on the
# list, 2026-11-16); any other wording is kept as a label of its sewage words, so a name typed there is never kept
# (Astra review 2026-11-16 P1-1)
SUBSTANCE_WORDS = {
    "a", "airplane", "and", "appears", "at", "be", "black", "blackwater", "de", "discharge", "domestic", "effluent",
    "from", "gray", "grey", "hauled", "human", "icer", "if", "investigating", "is", "it", "leak", "not", "only", "or",
    "other", "overflow", "partially", "port", "possibly", "potty", "present", "raw", "sanitary", "septage", "septic",
    "sewage", "sewer", "sewerage", "sewere", "sludge", "sure", "tank", "the", "time", "to", "treated", "unsure",
    "untreated", "waste", "wastewater", "wastewtaer", "water", "with", "strong", "odor", "odour", "spill", "line",
    "main", "lift", "station", "manhole", "backup", "unknown", "possible", "portable", "toilet", "johns", "john"}
WATER_WORDS = re.compile(r"\b(?:river|creek|lake|reservoir|pond|ponds|slough|draw|ditch|narrows|spring|springs|fork|"
                         r"stream|tributary|drainage|canal|wash|gulch|run|branch|wetlands?|marsh|lagoon|basin|bay|"
                         r"inlet|outlet|channel|brook)\b", re.I)
CAP_RUN = re.compile(r"\b[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*)+")


def substance_label(v) -> str | None:
    """The substance as filed when every word is a substance word, else its sewage words as a label."""
    s = clean(v)
    if not s:
        return None
    words = re.findall(r"[a-z]+", s.lower())
    if words and all(w in SUBSTANCE_WORDS for w in words) and not re.search(r"\d{3}|@", s):
        return s
    found = []
    for m in SEWAGE_WORDS.finditer(s):
        t = m.group(0).lower()
        if t not in found:
            found.append(t)
    return (", ".join(found) + " (the filer's wording is not reproduced)") if found else None


def names_only_waters(s: str) -> bool:
    """Every run of two or more capitalised words is a water's name: it holds a water word, or one follows it
    ("North Platte river"). A run that is not ("near Pat Example") may be a person."""
    for m in CAP_RUN.finditer(s):
        after = s[m.end():m.end() + 20]
        if not WATER_WORDS.search(m.group(0)) and not re.match(r"\s+(?:\w+\s+)?(?:river|creek|lake|reservoir)\b",
                                                                  after, re.I):
            return False
    return True

clean = mi.clean
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?[ ]{1,2}[A-Z][A-Za-z'-]+(?:[ ]{1,2}[A-Z][A-Za-z'-]+)?")
NAME_VERB = re.compile(r"\b([A-Z][a-z'-]+[ ]{1,2}[A-Z][a-z'-]+)(?=[ ]{1,2}(?:reported|called|stated|said|notified|"
                       r"contacted|observed|noticed|discovered)\b)")


def scrub_free(v) -> str | None:
    """Filer text as a record keeps it: e-mails, telephones, house numbers, owners' and people's names cut; a value
    that is only a person's name becomes [name removed]."""
    s = mi.free_text(clean(v))
    s = HONORIFIC.sub(NAME_REMOVED, s)
    s = NAME_VERB.sub(lambda m: m.group(0) if mi._site_words(m.group(1)) else NAME_REMOVED, s)
    s = clean(s)
    if s and s != NAME_REMOVED and mi._person(s):
        return NAME_REMOVED
    return s or None


def parse_time(v) -> tuple[datetime | None, str | None]:
    """'2026-06-25 10:25:00' -> (aware Mountain time, 'minute'); '... 00:00:00' -> (that day's midnight, 'day')."""
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?", clean(v))
    if not m:
        return None, None
    try:
        dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4) or '00'}")
    except ValueError:
        return None, None
    prec = "day" if (dt.hour, dt.minute, dt.second) == (0, 0, 0) else "minute"
    return dt.replace(tzinfo=MOUNTAIN), prec


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def norm_name(v) -> str:
    s = clean(v).lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def operator_index(rows: list[dict] | None = None) -> dict[str, tuple[str, str]]:
    """normalised name -> (id, name) of the Wyoming rows of data/dischargers.json (a name two rows hold maps to
    neither)."""
    if rows is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
    seen: dict[str, set] = defaultdict(set)
    for r in rows:
        if isinstance(r, dict) and r.get("state") == "WY" and r.get("name"):
            seen[norm_name(r["name"])].add((r["id"], r["name"]))
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def key_base(r: dict) -> str | None:
    code = clean(r.get("IncidentCode"))
    if not code:
        return None
    county = re.sub(r"[^a-z0-9]+", "-", clean(r.get("County")).lower()).strip("-") or "nocounty"
    return f"{code}-{county}"


def row_keys(rows: list[dict]) -> list[str | None]:
    """Each row's key: IncidentCode, county and a hash of ClosureDate (DEQ's closing stamp, to the second; a corrected
    incident date keeps the key), whichever rows are read with it (Astra review 2026-11-16 P1-2: a suffix added only on a collision changed
    an id when a second row appeared). Rows that still share a key are found by build() and left unread."""
    out = []
    for r in rows:
        b = key_base(r)
        if b:
            b = f"{b}-{hashlib.sha256(clean(r.get('ClosureDate')).encode()).hexdigest()[:6]}"
        out.append(b)
    return out


def _words(row: dict) -> str:
    """The in-memory text the rules read (never kept): substance, cause and description."""
    return " ".join(clean(row.get(k)) for k in ("SubstanceOther", "CauseDescription", "CauseOther", "AdditionalInfo"))


def _desc(row: dict) -> str:
    return " ".join(clean(row.get(k)) for k in ("CauseOther", "AdditionalInfo"))


def _affirmed(rx: re.Pattern, text: str) -> bool:
    """rx matches text somewhere not preceded by a negation ("no sewage", "not going into a sanitary sewer")."""
    return any(not NEGATED.search(text[max(0, m.start() - 40):m.start()]) for m in rx.finditer(text))


# ---------------------------------------------------------------- the sewage rule

def classify(row: dict) -> tuple[str, str]:
    """('sewage', basis), ('left out', kind), ('bloom', '') or ('other', '') for a row of the list."""
    sub = clean(row.get("Substance"))
    text = clean(row.get("SubstanceOther"))
    if sub == BLOOM:
        return "bloom", ""
    if sub not in ("Other", "Hazardous Substance"):
        return "other", ""
    if text and not PLACEHOLDER_SUBSTANCE.match(text) and SEWAGE_WORDS.search(text):
        strong = STRONG.search(text)
        if INDUSTRIAL.search(text) and not SEWAGE_ITSELF.search(text):
            return "left out", "industrial, oily or chemical wastewater"
        if TREATED.search(text) and not strong:
            return "left out", "treated wastewater"
        if ODOUR.search(text):
            return "left out", "odour report"
        if not strong and not re.search(r"sewer|gr[ae]y ?water", text, re.I) and GENERIC_ONLY.search(text):
            desc = _desc(row)
            if _affirmed(SEWER_CUES, desc) and not INDUSTRIAL_DESC.search(desc):
                return "sewage", ("the substance as filed is wastewater or effluent, and the report's cause or "
                                  "description names sewer works")
            return "left out", "wastewater not shown to be sewage"
        return "sewage", "the substance as filed names sewage"
    if not text or PLACEHOLDER_SUBSTANCE.match(text):
        desc = _desc(row)
        if _affirmed(DESC_SEWAGE, desc) and not INDUSTRIAL_DESC.search(desc):
            return "sewage", ("the list gives no substance; the report's cause or description says sewage was "
                              "released")
    return "other", ""


# ---------------------------------------------------------------- records

def water_text(row: dict, flag: str) -> tuple[str | None, str | None, bool]:
    """(the water as filed or None, why none, the text itself begins 'Yes')."""
    raw = clean(row.get("WaterAffected"))
    if not raw:
        return None, None, False
    yes = bool(YES_PREFIX.match(raw))
    if flag == "no" and not yes:
        return None, "the list says the spill did not reach water", False
    s = YES_PREFIX.sub("", raw) if yes else raw
    if not s or NO_WATER_TEXT.match(s) or mi.WATER_NONE.match(s):
        return None, "the water text names no water", yes
    s = scrub_free(s)
    if not s or s == NAME_REMOVED:
        return None, "the water text names no water", yes
    if NOT_REACHED.search(s):
        return None, "the water text does not say a water was reached", yes
    if TRIBUTARY_OF.search(s):
        return None, (f"the water text names a tributary or drainage of another water ({s!r}): a different water, so "
                      "the water it names is not used"), yes
    if len(s) > WATER_TEXT_MAX:
        return None, "the water text is an account, not a water's name, and is not reproduced", yes
    if HOME_WORDS.search(s):
        return None, "the water text describes private property and is not reproduced", yes
    if not names_only_waters(s):
        return None, "the water text holds words that may name a person and is not reproduced", yes
    return s, None, yes


def point_of(row: dict, public: bool, home: bool) -> tuple[float | None, float | None, str | None]:
    """(lat, lon, None) rounded to POINT_DECIMALS, or (None, None, why the point is not kept)."""
    la, lo = clean(row.get("Latitude")), clean(row.get("Longitude"))
    if not la and not lo:
        return None, None, None
    try:
        lat, lon = float(la), float(lo)
    except ValueError:
        return None, None, "the list's coordinates are not numbers"
    if not (WY_BOX[1] <= lat <= WY_BOX[3] and WY_BOX[0] <= lon <= WY_BOX[2]):
        return None, None, "the list's point lies outside Wyoming"
    decimals = min(len((x.split(".") + [""])[1].rstrip("0")) for x in (la, lo))
    if decimals < POINT_DECIMALS:
        return None, None, "the list's point has fewer than three decimals"
    if home:
        return None, None, "the report describes a home or private property: no point is kept"
    if not public:
        return None, None, "the report does not name public sewer works: no point is kept"
    county = clean(row.get("County"))
    if not county:
        return None, None, "the report gives no county to check the point against: no point is kept"
    from build import status as S
    here = S.point_county("WY", lat, lon)
    if here is None or not re.sub(r"\s+county$", "", here[1], flags=re.I).lower() == county.lower():
        return None, None, f"the list's point lies outside {county} County, the county the list gives"
    return round(lat, POINT_DECIMALS), round(lon, POINT_DECIMALS), None


def tie(row: dict, operators: dict, public: bool, home: bool) -> tuple[tuple[str, str] | None, str]:
    name = norm_name(UTILITY_SUFFIX.sub("", clean(row.get("CompanyName"))))
    hit = operators.get(name) if name else None
    if hit and public and not home:
        return hit, ("the list names this system as the responsible party (its name as on this site's operator list), "
                     "on a report of its sewer works")
    if hit:
        return None, ("the list's responsible party has the name of an operator on this site's list, but the report "
                      "does not describe that operator's sewer works, so no operator is named")
    return None, ("no operator is named: the list's responsible party is not reproduced (the field can hold a private "
                  "person or a company)")


def volume(row: dict) -> tuple[int | None, str | None, str | None]:
    q, unit, other = clean(row.get("SubstanceQuantity")), clean(row.get("SubstanceUnit")), clean(row.get("UnitOther"))
    f = mi.fnum(q) if q else None
    u = scrub_free(other) if unit.lower() == "other" and other else (unit or None)
    text = None
    if f is not None:
        n = f"{f:,.2f}".rstrip("0").rstrip(".")
        if unit.lower() == "other":
            text = f"{n} ({u})" if u and u != NAME_REMOVED else f"{n} (unit not given)"
        else:
            text = f"{n} {unit.lower()}" if unit else f"{n} (unit not given)"
    elif u and u != NAME_REMOVED:
        text = f"quantity not given ({u.lower()})"
    gal = int(round(f)) if f is not None and f > 0 and unit.lower() == "gallons" else None
    why = "the list gives 0" if f == 0 else None
    return gal, text, why


TRACKED = ("IncidentDate", "Substance", "SubstanceOther", "SubstanceQuantity", "SubstanceUnit", "SpillReachedWater",
           "WaterAffected", "County", "Latitude", "Longitude")


def kept_row(row: dict) -> dict:
    return {k: clean(row.get(k)) or None for k in KEPT}


def build_record(row: dict, key: str, basis: str, fetched_at: str, prev: dict | None, operators: dict) -> dict:
    words = _words(row)
    home = bool(HOME_WORDS.search(words)) or bool(re.search(r"septic|port[a-]?(?:a[- ]?)?potty|portable toilet",
                                                           clean(row.get("SubstanceOther")), re.I))
    public = bool(_affirmed(PUBLIC_WORKS, words))
    flag = clean(row.get("SpillReachedWater")).lower()
    a = kept_row(row)
    water, no_water_why, text_yes = water_text(row, flag)
    tied, tie_basis = tie(row, operators, public, home)
    lat, lon, why_no_point = point_of(row, public or bool(tied), home)
    a["Latitude"], a["Longitude"] = (str(lat) if lat is not None else None), (str(lon) if lon is not None else None)
    a["WaterAffected"] = water
    a["SubstanceOther"] = substance_label(scrub_free(row.get("SubstanceOther")))
    a["UnitOther"] = scrub_free(row.get("UnitOther")) if clean(row.get("UnitOther")) else None
    a["IncidentCity"] = clean(row.get("IncidentCity")).title() or None
    p_raw = (prev or {}).get("raw") or {}
    raw = dict(a)
    raw["_withheld"] = WITHHELD_NOTE
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or fetched_at
    revs = list(p_raw.get("_revisions") or [])
    if p_raw and any((p_raw.get(k) or None) != (a.get(k) or None) for k in TRACKED):
        revs.append({"seen_until": (prev or {}).get("fetched_at"), **{k: p_raw.get(k) for k in TRACKED}})
    if revs:
        raw["_revisions"] = revs[-10:]
    raw["state"] = "WY"
    raw["county"] = clean(row.get("County")) or None
    raw["place"] = a["IncidentCity"]
    raw["closure_date"] = clean(row.get("ClosureDate")) or None
    raw["_closure_basis"] = "ClosureDate: DEQ's closing of the report, not the end of the spill"
    raw["_sewage_basis"] = basis
    sub_text = a["SubstanceOther"] if a["SubstanceOther"] and not PLACEHOLDER_SUBSTANCE.match(a["SubstanceOther"]) \
        else None
    raw["_type_basis"] = ((f"the list's substance: {sub_text!r}" if sub_text else
                           f"the list gives no substance (its category: {clean(row.get('Substance'))!r}); the report's "
                           "description says sewage")
                          + ("; a septic tank, portable toilet or private line, not a public sewer" if home else ""))
    raw["reached_water_answer"] = clean(row.get("SpillReachedWater")) or None
    raw["_reached_water_note"] = ("the list's 'reached water' answer (its columns SpillCouldReachWater and "
                                  "SpillReachedWater repeat one answer)")
    if flag == "yes":
        raw["reached_water"], raw["_placement"] = True, "own_place_only"
    elif flag == "no" and text_yes and water:
        raw["reached_water"], raw["_placement"] = "text", "named_water_only"
        raw["_reached_water_basis"] = "the list answers No, but its water text begins 'Yes' and names a water"
    elif flag == "no":
        raw["reached_water"], raw["_placement"] = False, "named_water_only"
        raw["_no_water_reason"] = "the list says the spill did not reach water"
    else:
        raw["reached_water"], raw["_placement"] = None, "named_water_only"
    if no_water_why and clean(row.get("WaterAffected")):
        raw["_water_text_note"] = no_water_why
    if why_no_point:
        raw["_point_withheld"] = why_no_point
    raw["_discharger_basis"] = tie_basis
    gal, vtext, vwhy = volume(row)
    if vwhy:
        raw["_volume_not_used"] = vwhy
    base = dict(source_id=SOURCE_ID, source_record_id=key, fetched_at=fetched_at, source_url=URL)
    start, prec = parse_time(row.get("IncidentDate"))
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    if start is not None and start > fetched + timedelta(days=1):
        raw["_start_not_used"] = (f"the incident date as published ({clean(row.get('IncidentDate'))}) lies after the "
                                  "list was read; the report is kept with no start")
        start, prec = None, None
    raw["start_basis"] = ("IncidentDate: the incident's date and time as filed with DEQ, in Mountain time"
                          + ("; midnight is the list's form of a date with no time, so the start is that day"
                             if prec == "day" else ""))
    raw["_end_basis"] = "the list gives no end; DEQ's 'Complete' is the report's status, not the spill's"
    return event(
        **base, event_type="sso", status="unknown",
        discharger_id=tied[0] if tied else None, discharger_name=tied[1] if tied else None, npdes_permit=None,
        outfall_id=None, outfall_name=None,
        waterbody_text=water if flag != "no" or raw["reached_water"] == "text" else None,
        water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        coord_precision_m=100 if lat is not None else None,
        started_at=iso(start), ended_at=None, time_precision=prec,
        reported_at=None, published_at=None, source_updated_at=None,
        material=sub_text, volume_gal=gal, volume_text=vtext, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error=None,
    )


def copy_links(rows: list[dict], keys: list[str | None]) -> dict[str, tuple[str, str]]:
    """{key of a copy: (key that stands, closure gap)}: rows identical in every column of the list (compared in memory,
    the withheld columns included) but IncidentCode and ClosureDate, with a minute-precision incident time and a
    quantity, closed by DEQ within five minutes of each other. The first code stands."""
    groups = defaultdict(list)
    for row, key in zip(rows, keys):
        if not key or parse_time(row.get("IncidentDate"))[1] != "minute" or not clean(row.get("SubstanceQuantity")):
            continue
        groups[tuple(clean(row.get(k)) for k in HEADER if k not in ("IncidentCode", "ClosureDate"))].append((row, key))
    out = {}
    for rs in groups.values():
        if len(rs) < 2:
            continue
        rs.sort(key=lambda x: (clean(x[0].get("IncidentCode")), x[1]))
        t0 = parse_time(rs[0][0].get("ClosureDate"))[0]
        for row, key in rs[1:]:
            t = parse_time(row.get("ClosureDate"))[0]
            if t0 is not None and t is not None and abs((t - t0).total_seconds()) <= 300:
                out[key] = (rs[0][1], f"{abs((t - t0).total_seconds()):.0f} s")
    return out


def build(rows: list[dict], fetched_at: str, prev_records: list[dict], operators: dict | None = None,
          complete_read: bool = True, left_state: dict | None = None) -> tuple[list[dict], dict, list[str]]:
    """rows: the list's rows of this read (every column, in memory). Records of earlier runs not read again are kept as
    past reports. Returns (records, stats, the keys of sewage rows whose incident date could not be read)."""
    operators = operator_index() if operators is None else operators
    left_state = left_state if left_state is not None else {}
    prev = {r["event_id"]: r for r in prev_records if isinstance(r, dict) and r.get("event_id")}
    records, seen, unread = [], set(), []
    kinds, left_now, blooms = Counter(), Counter(), []
    keys = row_keys(rows)
    copies = copy_links(rows, keys)
    shared = {k for k, n in Counter(k for k in keys if k).items() if n > 1}
    for row, key in zip(rows, keys):
        if not key:
            continue
        kind, basis = classify(row)
        kinds[kind] += 1
        if kind == "bloom":
            blooms.append(clean(row.get("IncidentDate")))
            continue
        if kind == "other":
            continue
        if kind == "left out":
            left_state[key] = basis
            left_now[basis] += 1
            continue
        eid = f"{SOURCE_ID}:{key}"
        if eid in seen:
            continue
        seen.add(eid)
        left_state.pop(key, None)
        if key in shared or parse_time(row.get("IncidentDate"))[0] is None:
            # two rows with one key (Astra P1-3), or a date that cannot be read: the earlier record is kept as it was
            unread.append(key)
            if eid in prev:
                records.append(prev[eid])
            continue
        rec = build_record(row, key, basis, fetched_at, prev.get(eid), operators)
        if key in copies:
            rec["duplicate_of"] = f"{SOURCE_ID}:{copies[key][0]}"
            rec["raw"]["_duplicate_basis"] = (f"the same report filed twice (every field the same, closed by DEQ "
                                              f"{copies[key][1]} apart); {rec['duplicate_of']} stands")
        records.append(rec)
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        key = eid.split(":", 1)[1]
        if key in left_state:               # a rule now leaves it out: not kept
            continue
        r = json.loads(json.dumps(r))
        if complete_read:
            r["raw"]["_missing_from_list_since"] = r["raw"].get("_missing_from_list_since") or fetched_at
        records.append(r)
        kept += 1
    dups = sum(1 for r in records if r.get("duplicate_of"))
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"rows_read": sum(kinds.values()), "sewage_rows": kinds["sewage"], "kept_from_earlier_runs": kept,
             "copies": dups, "bloom_rows": kinds["bloom"], "newest_bloom_row": max(blooms, default=None),
             "reached_water_yes": sum(1 for r in records if (r.get("raw") or {}).get("reached_water") is True),
             "with_point": sum(1 for r in records if r.get("lat") is not None),
             "names_water": sum(1 for r in records if r.get("waterbody_text")),
             "with_operator_row": sum(1 for r in records if r.get("discharger_id")),
             "left_out_this_run": dict(left_now), "statewide": True}
    return records, stats, unread


# ---------------------------------------------------------------- reading

LEFT_OUT_NOTE = ("The list holds spills of every substance; we show its sewage reports. These counts are of the reports "
                 "that use a sewage or wastewater word and are not shown: industrial, oily or chemical wastewater, "
                 "treated wastewater (outside our scope), odour complaints, and wastewater reports whose words do not "
                 "tie the release to a sewer. The list's bloom reports are counted, not shown here.")


class BadRead(Exception):
    """An answer that is not a complete reading of the list."""


def parse_csv(content: bytes) -> list[dict]:
    """Every row of the list as a dict of HEADER, or BadRead (module docstring, Reading and failure)."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise BadRead(f"the answer is not UTF-8 text (byte {e.start})") from None
    if not text.strip():
        raise BadRead("the list answered nothing: read as an outage")
    if not text.endswith(("\n", "\r")):
        raise BadRead("the file does not end with a line break: read as cut short")
    try:
        table = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as e:
        raise BadRead(f"the file could not be read as CSV ({e}): read as cut short") from None
    if not table or table[0] != HEADER:
        got = table[0] if table else []
        raise BadRead(f"the header changed: {len(got)} columns, {len(set(got) ^ set(HEADER))} names differ from the "
                      f"{len(HEADER)} expected")
    bad = [i for i, r in enumerate(table[1:], 2) if len(r) != len(HEADER)]
    if bad:
        raise BadRead(f"{len(bad)} rows do not have {len(HEADER)} fields (first at line {bad[0]})")
    rows = [dict(zip(HEADER, r)) for r in table[1:]]
    if not rows:
        raise BadRead("the list answered a header and no rows: read as an outage")
    # an empty report: no code, no date, no substance (one on 2026-11-16, with only a quantity, media, divisions, status
    # and closure); a row with no code but a date or a substance cannot be keyed: the read fails (Astra P2-6)
    blank = sum(1 for r in rows if not any(clean(r[k]) for k in ("IncidentCode", "IncidentDate", "Substance",
                                                                 "SubstanceOther")))
    codeless = sum(1 for r in rows if not clean(r["IncidentCode"])) - blank
    if codeless:
        raise BadRead(f"{codeless} rows with other fields have no incident code (Astra review 2026-11-16 P2-6)")
    if blank > MAX_BLANK:
        raise BadRead(f"{blank} of {len(rows)} rows are blank")
    return rows


def check_count(rows: list[dict], last_complete: int | None) -> None:
    if last_complete and len(rows) < last_complete - min(MAX_DROP, max(1, MAX_DROP_SHARE * last_complete)):
        raise BadRead(f"the list answered {len(rows)} rows against {last_complete} in the last complete read: read as "
                      "cut short")


def fetch() -> bytes:
    """One ordinary request: no retry loop (the host is slow; the next run tries again)."""
    r = requests.get(URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    ctype = (r.headers.get("content-type") or "").lower()
    if "csv" not in ctype and "text/plain" not in ctype and "octet-stream" not in ctype:
        raise BadRead(f"the answer is {ctype or 'of no stated type'}, not CSV")
    return r.content


# ---------------------------------------------------------------- main

def due(doc: dict, now: datetime) -> bool:
    last = doc.get("last_ok_at") if doc.get("ok") else None
    if not last:
        return True
    try:
        t = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    return not (timedelta(0) <= now - t < timedelta(hours=EVERY_HOURS))


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved CSV instead of the list")
    ap.add_argument("--backfill", action="store_true", help="read the whole list now and record meta.backfill")
    ap.add_argument("--force", action="store_true", help=f"read now, not at most once in {EVERY_HOURS} hours")
    args = ap.parse_args(argv)
    events_path = EVENTS_DIR / f"{SOURCE_ID}.json"
    prev_doc = read_json(events_path, {}) or {}
    if not (args.file or args.backfill or args.force) and not due(prev_doc, datetime.now(UTC)):
        print(f"{SOURCE_ID}: read at {prev_doc.get('last_ok_at')}; next read after {EVERY_HOURS} hours")
        return 0
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    prev = prev_doc.get("records", [])
    t0 = time.monotonic()
    try:
        content = open(args.file, "rb").read() if args.file else fetch()
        rows = parse_csv(content)
        check_count(rows, None if args.file else state.get("last_complete_rows"))
    except Exception as e:  # noqa: BLE001 - every failure keeps the records
        msg = f"{type(e).__name__}: {scrub_text(str(e))[:300]}"
        write_events(SOURCE_ID, [], ok=False, error=msg,
                     meta={"completeness": {"failed_at": fetched_at, "last_complete_rows": state.get("last_complete_rows")}})
        print(f"{SOURCE_ID}: FAILED {msg}", file=sys.stderr)
        return 1
    took = round(time.monotonic() - t0, 1)
    left_state = state.setdefault("left_out", {})
    records, stats, unread = build(rows, fetched_at, prev, operator_index(), complete_read=not args.file,
                                   left_state=left_state)
    n_rows = len(rows)
    del rows, content                       # the full list (with its personal fields) is never kept
    records = redact.redact_events(records)
    raw_path = state.get("raw_path")
    if not args.file:
        kept = [{k: (r.get("raw") or {}).get(k) for k in KEPT} for r in records]
        sha = hashlib.sha256(json.dumps(kept, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            doc = {"url": URL, "fields": list(KEPT), "fetched_at": fetched_at, "rows_in_list": n_rows,
                   "sewage_rows": kept}
            raw_path = str(save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False), "json").relative_to(ROOT))
            state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
        state["last_complete_rows"] = n_rows
    if args.backfill:
        starts = sorted(r["started_at"] for r in records if r.get("started_at"))
        state["backfill"] = {"at": fetched_at, "rows": n_rows, "seconds": took,
                             "sewage_records": len(records),
                             "first_start": starts[0] if starts else None, "last_start": starts[-1] if starts else None,
                             "records_by_start_year": dict(sorted(Counter(
                                 (r.get("started_at") or "no start")[:4] for r in records).items()))}
    state["fetched_at"] = fetched_at
    write_json(STATE_FILE, state)
    newest = max((r.get("started_at") or "" for r in records), default="") or None
    meta = {**stats, "newest_start": newest, "raw_path": raw_path, "page": PAGE_URL, "url": URL,
            "time_basis": "Incident dates as the list gives them, read in Mountain time (America/Denver).",
            "credit": CREDIT, "registry_ids": REGISTRY_IDS, "cadence": f"read at most once in {EVERY_HOURS} hours",
            "left_out": dict(Counter(left_state.values())),
            "left_out_note": LEFT_OUT_NOTE,
            "completeness": {"rows_this_read": n_rows, "max_drop": [MAX_DROP, MAX_DROP_SHARE]},
            "backfill": state.get("backfill"), "seconds": took}
    path_notes_to_meta(records, meta)
    meta["unread"] = sorted(unread) or None
    err = (f"{len(unread)} sewage row(s) give an incident date that is not a time; an earlier record of each is kept "
           "as it was and read again next run") if unread else None
    path = write_events(SOURCE_ID, records, ok=not unread, error=err, meta=meta, partial=bool(unread))
    print(f"{SOURCE_ID}: {stats['rows_read']} rows read ({took} s), {stats['sewage_rows']} sewage, "
          f"{stats['kept_from_earlier_runs']} kept from earlier; reached water {stats['reached_water_yes']}; "
          f"point {stats['with_point']}; operator {stats['with_operator_row']}; copies {stats['copies']} -> {path}")
    return 1 if unread else 0


if __name__ == "__main__":
    sys.exit(main())
