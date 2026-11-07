"""Shared helpers for the DirtyWaterWatch pipeline. Run modules from pipeline/ (python -m ingest.x).

Conventions (docs/plan.md §3 and §5): one JSON events file per source in data/build/events/, raw
responses in data/raw/<source>/, personal fields stripped, nothing invented.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
BUILD_DIR = DATA_DIR / "build"
EVENTS_DIR = BUILD_DIR / "events"
OUT_DIR = ROOT / "out"
SOURCES_DIR = DATA_DIR / "sources"

HEADERS = {"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org; admin@infobakery.com)"}
BROWSER_HEADERS = {  # some state hosts (maine.gov, des.nh.gov) answer only a browser user agent
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

EVENT_TYPES = {"cso", "sso", "bypass", "blended", "plant_bypass", "beach_advisory", "beach_closure",
               "hab_advisory", "shellfish_closure", "rain_advisory", "annual_total", "unknown"}
STATUSES = {"ongoing", "ended", "unknown", "advisory_active", "advisory_lifted"}
_BY = r"[\s_-]?by"
PERSONAL_KEYS = re.compile(rf"(reporter|contact|created{_BY}|submitted{_BY}|modified{_BY}|uploaded{_BY}|updated{_BY}|operator|phone|"
                           rf"e-?mail|name_of|person|inspector|investigator|signed{_BY}|signer|signator|signature|"
                           rf"assigned[\s_-]?to|prepared{_BY}|reviewed{_BY}|approved{_BY}|certified{_BY}|entered{_BY})", re.I)
KEEP_KEYS = re.compile(r"(class|type|category|count|id)$", re.I)   # reporterClass, operatorType: a kind, not a person
NAME_KEYS = re.compile(r"^(first|last|middle|full|given|family|sur)[_ -]?name$|^surname$|^(fname|lname)$", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# a number range followed by a unit ("500-1000 feet", "100-1500 gallons", "830-1030 am") is not a phone number;
# only the short form can be a range: a ten-digit number followed by "hours" or "am" is still a phone number
_NOT_A_RANGE = (r"(?!\s*(?:-|to\b)?\s*(?:(?:feet|foot|ft|yards?|yds?|miles?|meters?|metres?|km|inch(?:es)?|"
                r"gallons?|gals?|gal|mg|mgd|gpm|gpd|liters?|litres?|cfs|lbs?|pounds?|tons?|hours?|hrs?|minutes?|"
                r"mins?|seconds?|secs?|days?|am|pm|percent)\b|a\.m\.|p\.m\.|%))")
# not the decimals of a coordinate ("-86.512345 1234 Example Rd" is a longitude and a house number)
PHONE_RE = re.compile(r"(?<![\w-])(?<!\d\.)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]\d{4}(?![\w-])"
                      r"|(?<![\w-])\d{3}[.-]\d{4}(?![\w-])" + _NOT_A_RANGE, re.I)
# Staff names inside free text: "Inspector Eddy", "Investigator Tom Watson", "contact Jane Doe at ...".
# A name is one to three capitalised words or initials (an optional Mr/Ms/Dr first); common words that
# follow these titles without being a name ("Inspector General", "Contact Tank at") are not taken.
_NAME = r"(?:(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+)?(?:[A-Z]\.|[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)*)(?:\s+(?:[A-Z]\.|[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)*)){0,2}"
_NOT_NAME = (r"(?!(?:The|A|An|And|Or|Of|On|At|In|To|For|From|With|By|Was|Were|Is|Are|Has|Had|Will|Would|General|"
             r"Report|Reports|Office|Department|Dept|Division|Service|Services|Unit|Team|Staff|Program)\b)")
_NOT_CONTACT = (r"(?!(?:Tank|Tanks|Chamber|Chambers|Basin|Basins|Time|Point|Customer|Customers|City|Town|Village|"
                r"Police|Fire|Public|Us|Our|Your|Information|Info|Center|Centre|Desk|Line|Phone|Email)\b)")
# A phone number typed as ten digits with no separator ("my contact is 3055550123"), right after a contact word: PHONE_RE
# needs a separator so that ids, dates and counts are not taken; a North American number never starts with 0 or 1, nor
# does its exchange
CONTACT_DIGITS_RE = re.compile(r"(\b(?i:contact|phone|telephone|tel|cell(?:phone)?|mobile|call|text|reach(?:ed)?|ph)\b[^\d\n]{0,20}?)"
                               r"(?<!\d)(?:\+?1[\s.-]?)?[2-9]\d{2}[2-9]\d{6}(?!\d)")
# A house number tied to a residence or a resident ("a resident at 905 N Sample Ct", "the home @ 3446 Sample Rd",
# "behind the house located at 105 Elm Dr", "two homes at 105 and 107 Pine Circle", "a homeowner's sewer line at 501 Oak
# Ave"): the number identifies a household, so it goes and the street stays (the place of the spill). A number tied to a
# manhole, a lift station or a business is not touched.
_HOME = (r"(?:residents?|residences?|home[ ]?owners?|homeowner's|home|homes|house|houses|single[- ]family[ ]home|tenants?|"
         r"occupants?|complainants?|callers?|customers?|neighbou?rs?|property[ ]owners?|dwelling|duplex|townhome|condo)")
_HOME_THING = r"(?:(?:front|back|rear|side)[ ])?(?:yard|property|lot|driveway|cleanout|clean-out|lateral|service[ ]line|sewer[ ]line|line)"
_HOUSE_NO = r"\d{1,6}[A-Za-z]?(?![\d:/.,-]\d)"
RESIDENCE_NUMBER_RE = re.compile(
    rf"(\b(?i:{_HOME})(?:'s?)?(?:[ ](?i:{_HOME_THING}))?[ ]{{0,2}}\(?[ ]{{0,2}}"
    rf"(?:(?i:located|living|residing|situated)[ ]{{1,2}})?(?:(?i:at|@|of|on|in[ ]front[ ]of|behind)[ ]{{0,2}})?"
    rf"(?:(?i:or[ ]near|or[ ]close[ ]to)[ ]{{1,2}})?[ ]{{0,2}},?[ ]{{0,2}})"
    rf"({_HOUSE_NO}(?:[ ]{{0,2}},[ ]{{0,2}}(?:(?i:and|&)[ ]{{1,2}})?{_HOUSE_NO}|[ ]{{1,2}}(?i:and|&)[ ]{{1,2}}{_HOUSE_NO})*)"
    rf"(?=[ ]{{1,2}}(?:[NSEW]\.?[ ]{{1,2}})?(?:[A-Z]|\d{{1,3}}(?i:st|nd|rd|th)\b)"
    rf"(?![ ]{{0,2}}(?i:hrs?|hours|am|pm|a\.m|p\.m|gallons?|gals?|feet|ft|psi|gpm|inch|inches)\b))")
RESIDENCE_NUMBER_BEFORE_RE = re.compile(
    rf"(?<![\w.,/:-])({_HOUSE_NO})(?=[ ]{{1,2}}(?:[NSEW]\.?[ ]{{1,2}})?(?:[A-Za-z0-9][\w'.-]*[ ]{{1,2}}){{0,3}}[A-Za-z][\w'.-]*"
    rf"(?:[ ]{{1,2}}(?:N|S|E|W|NE|NW|SE|SW))?[ ]{{0,2}},[ ]{{0,2}}(?i:a|the|an)[ ]{{1,2}}(?i:home[ ]?owner|resident|tenant|occupant)s?\b)")
HOUSE_NUMBER_REMOVED = "[house number removed]"
# not a household: a building of a works or an institution ("Pump House 2", "the Gate House at 4650 ..."), a complex's
# name ("Example Apartment Homes at 100 ...", "Example Place Condo located at 120 ..."), or a count ("customers 1500")
_FACILITY_HOUSE = set("""pump well gate guard control meter valve screen chlorine blower generator power boat pool club court
state custom opera meeting chemical electrical switch fire bath ware ice pole field funeral nursing care""".split())
_COMPLEX_WORDS = {"homes", "condo", "condos", "condominium", "condominiums", "townhomes"}
_NOT_A_COMPLEX = {"the", "a", "an", "private", "new", "single", "our", "my", "his", "her", "their", "two", "three", "four",
                  "several", "family", "mobile"}
_HOME_TIE = re.compile(r"(?i)\b(?:at|of|on|in\s+front\s+of|behind|located|living|residing|situated)\b|@|\(")


def _is_residence(m: re.Match) -> bool:
    """A RESIDENCE_NUMBER_RE match that names a household's address (see _FACILITY_HOUSE)."""
    word = re.match(r"[A-Za-z]+", m.group(1)).group(0)
    prev = re.search(r"([A-Za-z]+)\W{0,3}$", m.string[max(0, m.start() - 30):m.start()])
    prev = prev.group(1) if prev else ""
    if prev.lower() in _FACILITY_HOUSE:
        return False
    if word.lower() in _COMPLEX_WORDS and word[0].isupper() and prev[:1].isupper() and prev.lower() not in _NOT_A_COMPLEX:
        return False
    if word.lower().endswith("s") and not _HOME_TIE.search(m.group(1)):
        return False                              # "customers 1500 ...", "residents 2 ...": a count
    return True
TITLE_NAME_RE = re.compile(rf"\b((?i:inspector|investigator))(\s+){_NOT_NAME}{_NAME}")
CONTACT_NAME_RE = re.compile(rf"\b((?i:contact(?:ed)?))(\s+){_NOT_NAME}{_NOT_CONTACT}{_NAME}(?=\s+(?i:at)\b)")
# A pipeline working note in a string: a path into this repository ("research/ri/dischargers.json",
# "data/raw/ri-nbc/"), not a web address and not ordinary words such as "flow data/pump speed".
_REPO_PATH = re.compile(r"(?<![\w./:-])(?:docs|data|research|pipeline|site|out)/[\w.<>-]+(?:/[\w.<>-]*)*")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
    tmp.replace(path)


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def discharger_alias_map(rows: list[dict]) -> dict[str, str]:
    """{alias: registry id} from the `aliases` of the registry rows (data/dischargers.json; a row built
    from research files, without `aliases`, contributes its `research_ids`). The ingesters stamp events
    with the id of the research file or a slug of the source's facility name; the registry keeps one row
    per permit, so the other ids are listed as aliases and the export rewrites them to the row's id.
    A row's own id is not an alias; an alias that is another row's id, or that two rows claim, maps
    to nothing (the row id wins; a contested alias is a question for the registry, not for the export)."""
    ids = {r.get("id") for r in rows if isinstance(r, dict)}
    claimed: dict[str, set[str]] = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        for a in [*(r.get("aliases") or []), *(r.get("research_ids") or [])]:
            if isinstance(a, str) and a and a != r["id"] and a not in ids:
                claimed.setdefault(a, set()).add(r["id"])
    return {a: next(iter(v)) for a, v in claimed.items() if len(v) == 1}


# ---------------------------------------------------------------- the live states

STATE_CODE = re.compile(r"[A-Z]{2}")


def rules_live_states(rules: dict | None) -> set[str] | None:
    """The live states of a rules document (data/rules.json `live_states`), upper case; None when it has no list."""
    v = (rules or {}).get("live_states") if isinstance(rules, dict) else None
    if not isinstance(v, list):
        return None
    out = {str(x).strip().upper() for x in v if isinstance(x, str) and STATE_CODE.fullmatch(str(x).strip().upper())}
    return out or None


def live_states(data_dir: Path | None = None) -> list[str]:
    """The states this site publishes: data/rules.json `live_states`, the one list (build/status.py states() returns
    it). LookupError when the file has none (callers fall back to status.states())."""
    d = Path(data_dir) if data_dir is not None else DATA_DIR
    try:
        rules = json.loads((d / "rules.json").read_text())
    except (OSError, ValueError) as e:
        raise LookupError(f"data/rules.json not read ({type(e).__name__})") from e
    live = rules_live_states(rules)
    if live is None:
        raise LookupError("data/rules.json has no live_states list")
    return sorted(live)


# ---------------------------------------------------------------- the outfall registry (docs/national-outfalls.md)

OUTFALL_REGISTRY_GLOB = "outfalls-*.json"
# provisional outfall records from the overflow reports themselves (a build product, written each build by another
# step): read after every official file, so an official row always wins the same permit and outfall
REPORTED_OUTFALLS = "build/outfalls-reported.json"
OUTFALL_KINDS = ("cso", "plant", "reported", "other")   # other: a row EPA flags CSO that is none (kind_note says why)
PROVISIONAL_FIELDS = ("record_status", "confidence", "report_count", "last_report_at", "event_ids", "reached_water",
                      "on_map")
# files the last load_outfall_registry() call could not read (a half-written file from another builder): "data/<name>: why"
OUTFALL_REGISTRY_SKIPPED: list[str] = []


def outfall_file_rank(name: str) -> int:
    """How general a registry file is; the lower rank wins a duplicate outfall: a regional file (outfalls-new-england.json,
    outfalls-mid-atlantic.json, or any other region) 0, the national CSO file (outfalls-us.json, outfalls-*-us.json)
    1, a treatment-plant file (outfalls-plants-us.json, any name with "plants") 2, so a plant row never replaces a
    combined sewer row; the provisional records from overflow reports (REPORTED_OUTFALLS) 3, below every official
    file."""
    if name.replace("\\", "/").endswith(REPORTED_OUTFALLS) or Path(name).name == Path(REPORTED_OUTFALLS).name:
        return 3
    stem = Path(name).stem.lower()
    if "plants" in stem:
        return 2
    if stem == "outfalls-us" or stem.endswith("-us"):
        return 1
    return 0


def outfall_number(outfall) -> str:
    """An outfall number as the registry compares it: upper case, spaces dropped, leading zeros dropped ("001" and
    "1" are one outfall, "01A" and "001A" too; "000" is "0")."""
    s = re.sub(r"\s+", "", str(outfall if outfall is not None else "")).upper()
    return s.lstrip("0") or ("0" if s else "")


def outfall_key(permit, outfall) -> tuple[str, str]:
    return (str(permit or "").strip().upper(), outfall_number(outfall))


def _closed(row: dict) -> bool:
    return str(row.get("outfall_status") or "").upper().startswith("CLS")


def is_provisional(row: dict) -> bool:
    """A provisional outfall record (a place from the overflow reports, not an official listing)."""
    return bool(row.get("record_status")) and row.get("record_status") != "official"


def load_outfall_registry(data_dir: Path | None = None, provisional: bool = True) -> list[dict]:
    """Every outfall of every registry file (data/outfalls-*.json), once each: one row per (permit, outfall number
    with leading zeros dropped). A row from a more specific file wins (outfall_file_rank: regional over national
    over plants); within one file the first row wins, unless it is closed and a later one is not. Each row is a copy
    with `_file` ("data/<name>"), `outfall_kind` ("cso" unless the row says otherwise; every row of a plants file is
    "plant") and `country` ("US" unless the row says otherwise). A file that cannot be read (half-written by another
    builder) is skipped and named in OUTFALL_REGISTRY_SKIPPED; the others still load. The registry is national: the
    public outputs keep the live states only (build/status.py states()).

    provisional (the default): also the provisional records from the overflow reports (data/build/outfalls-
    reported.json, docs/national-outfalls.md): kind "reported" (or "cso" for a reported combined sewer outfall),
    `record_status` (provisional / confirmed; superseded rows are left out), each place a row of its own (its
    operator by permit, else discharger_id; water_slug the first of its water_slugs, match its water_match). An
    official row always wins: a place whose own permit and outfall, or every outfall its reports name
    (outfall_ids), the official files hold is left out. A missing file is no problem."""
    d = Path(data_dir) if data_dir is not None else DATA_DIR
    OUTFALL_REGISTRY_SKIPPED.clear()
    files = sorted(d.glob(OUTFALL_REGISTRY_GLOB), key=lambda p: (outfall_file_rank(p.name), p.name))
    if provisional and (d / REPORTED_OUTFALLS).exists():
        files.append(d / REPORTED_OUTFALLS)
    kept: dict[tuple[str, str], dict] = {}
    for p in files:
        rel = str(p.relative_to(d)) if p.is_relative_to(d) else p.name
        rank = 3 if rel == REPORTED_OUTFALLS else outfall_file_rank(p.name)
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            OUTFALL_REGISTRY_SKIPPED.append(f"data/{rel}: not read ({type(e).__name__})")
            continue
        rows = doc.get("outfalls") if isinstance(doc, dict) else doc
        if not isinstance(rows, list):
            OUTFALL_REGISTRY_SKIPPED.append(f"data/{rel}: no outfall list")
            continue
        # a plants file lists the sewerage-code permits that are no sewage plant (excluded_not_sewage: a water plant's
        # backwash, a construction project); a row of one that reaches the outfall list anyway is never read
        not_sewage = {str(x.get("npdes_permit") or "").strip().upper() for x in
                      (doc.get("excluded_not_sewage") if isinstance(doc, dict) else None) or [] if isinstance(x, dict)}
        for i, o in enumerate(rows):
            if not isinstance(o, dict):
                continue
            if not_sewage and str(o.get("npdes_permit") or "").strip().upper() in not_sewage:
                continue
            if rank == 3:
                if str(o.get("record_status") or "provisional") == "superseded":
                    continue
                if not o.get("npdes_permit") and not o.get("discharger_id"):
                    continue
                kind = str(o.get("outfall_kind") or "reported").lower()
                row = {**o, "record_status": o.get("record_status") or "provisional"}
                if not row.get("water_slug") and isinstance(o.get("water_slugs"), list) and o["water_slugs"]:
                    row["water_slug"] = o["water_slugs"][0]
                row.setdefault("match", o.get("water_match"))     # the provisional step's own short code
                # an official row wins: the same permit and outfall, or every outfall the reports name at this place
                if o.get("npdes_permit"):
                    named = [outfall_key(o["npdes_permit"], x) for x in o.get("outfall_ids") or [] if str(x).strip()]
                    own = outfall_key(o["npdes_permit"], o.get("outfall"))
                    if (own[1] and own in kept) or (named and all(k in kept for k in named)):
                        continue
                key = ("place", str(o.get("id") or f"{o.get('discharger_id') or o.get('npdes_permit')}|"
                                    f"{o.get('lat')},{o.get('lon')}|{o.get('outfall') or i}"))
            else:
                if not o.get("npdes_permit") or o.get("aggregate_of"):
                    continue                    # aggregate_of: EPA lists the permit's outfalls once more as one row
                kind = "plant" if rank == 2 else str(o.get("outfall_kind") or "cso").lower()
                row = dict(o)
                key = outfall_key(o["npdes_permit"], o.get("outfall"))
            row.update({"_file": f"data/{rel}", "outfall_kind": kind if kind in OUTFALL_KINDS else "cso",
                        "country": str(o.get("country") or "US").upper()})
            cur = kept.get(key)
            if cur is None:
                kept[key] = row | {"_rank": rank}
            elif cur["_rank"] == rank and cur["_file"] == row["_file"] and _closed(cur) and not _closed(row):
                kept[key] = row | {"_rank": rank}
    return [{k: v for k, v in r.items() if k != "_rank"} for r in kept.values()]


def save_raw(source_id: str, content: bytes | str, ext: str) -> Path:
    """Keep every fetched response: data/raw/<source>/<utc stamp>.<ext>."""
    p = RAW_DIR / source_id / f"{stamp()}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode())
    return p


def scrub_text(v: str) -> str:
    """Emails and phone numbers inside free text become [email removed] / [phone removed] (a number typed without
    separators too, after a contact word); staff names after "Inspector" / "Investigator", and in "contact <Name> at",
    become [name removed]; the house number of an address tied to a residence or a resident becomes
    [house number removed] (scrub_residence_numbers)."""
    v = EMAIL_RE.sub("[email removed]", v)
    v = CONTACT_DIGITS_RE.sub(r"\1[phone removed]", v)
    return scrub_residence_numbers(scrub_names(PHONE_RE.sub("[phone removed]", v)))


def residence_numbers(v: str) -> list[tuple[str, str | None]]:
    """[(house number, the street word after it)] of every address RESIDENCE_NUMBER_RE ties to a residence or a
    resident, so that the same address can be cut from another field of the record."""
    out = []
    for m in RESIDENCE_NUMBER_RE.finditer(v):
        if not _is_residence(m):
            continue
        nxt = re.match(r"[ ]{1,2}((?:[NSEW]\.?[ ]{1,2})?[\w']+)", v[m.end():])
        out += [(n, nxt.group(1) if nxt else None) for n in re.findall(r"\d{1,6}[A-Za-z]?", m.group(2))]
    for m in RESIDENCE_NUMBER_BEFORE_RE.finditer(v):
        nxt = re.match(r"[ ]{1,2}((?:[NSEW]\.?[ ]{1,2})?[\w']+)", v[m.end():])
        out.append((m.group(1), nxt.group(1) if nxt else None))
    return out


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


# any street address's house number ("5073 Sample Ave", "15 21st Street NW"): a notice filed by a member of the public
# keeps none (ingest/fl_dep_pnp.py), since the address is often the filer's home or a neighbour's
_STREET_WORD = (r"(?i:street|st|road|rd|avenue|ave|av|lane|ln|drive|dr|way|court|ct|place|pl|circle|cir|boulevard|blvd|blv|"
                r"highway|hwy|parkway|pkwy|terrace|ter|trail|trl|loop|run|cove|cv|path|point|pt|row|square|sq|crossing|xing|"
                r"pass|pike|bend|glen|grove|ridge|view|walk|lp|cswy|causeway)")
_ADDRESS_NUMBER = rf"(?<![\w.,/:-])\d{{1,6}}[A-Za-z]?"
_BEFORE_STREET_WORD = (rf"[ ]{{1,2}}(?:[NSEW]{{1,2}}\.?[ ]{{1,2}})?"
                       rf"(?:(?!(?i:and|or|to|from|of)\b)(?:[A-Za-z][\w'.-]*|\d{{1,3}}(?i:st|nd|rd|th)?)[ ]{{1,2}}){{1,3}}{_STREET_WORD}\b")
ADDRESS_NUMBER_RE = re.compile(rf"{_ADDRESS_NUMBER}(?={_BEFORE_STREET_WORD}"
                               rf"|[ ]{{1,2}}(?:[NSEW]{{1,2}}\.?[ ]{{1,2}})?[A-Z][a-z]+[ ]{{0,2}}(?:,|\.|$))")
# only a number followed by a street word ("12 Sample Lane"): a site's own number ("Site 3 North", "- 41 Bridge") stays
STREET_NUMBER_RE = re.compile(rf"{_ADDRESS_NUMBER}(?={_BEFORE_STREET_WORD})")
# a route or a mile marker, not a house number: "1234 N. 301 Hwy", "US 41", "Highway 17 Bridge", "Exit 131"
ROUTE_BEFORE = re.compile(r"(?i:\b(?:US|SR|CR|S\.?R\.?|C\.?R\.?|N|S|E|W|Hwy|Highway|Route|Rte|Interstate|I|Exit|Mile|Marker|"
                          r"MM|Road|Rd|Lot|Unit|Suite|Ste|Apt|Bldg|Building|Station|LS|PS|No|#))[ .#-]{0,3}$")


def strip_house_numbers(v: str, street_word_only: bool = False) -> str:
    """Every street address's house number in v becomes "[house number removed]" (ADDRESS_NUMBER_RE; with
    street_word_only, only a number followed by a street word, STREET_NUMBER_RE: for a name that is a site's own, where
    "Site 3 North" or "- 41 Bridge" is the site and not an address)."""
    v = (STREET_NUMBER_RE if street_word_only else ADDRESS_NUMBER_RE).sub(lambda m: m.group(0) if ROUTE_BEFORE.search(v[max(0, m.start() - 14):m.start()])
                              else HOUSE_NUMBER_REMOVED, v)
    # the numbers listed before it ("the buildings at 226, 224 and 220 Sample Ave")
    return re.sub(rf"(?<![\w.,/:-])(?:\d{{1,6}}[A-Za-z]?[ ]{{0,2}}(?:,[ ]{{0,2}}(?:(?:and|&)[ ]{{1,2}})?|[ ]{{1,2}}(?:and|&)[ ]{{1,2}}))+"
                  rf"(?={re.escape(HOUSE_NUMBER_REMOVED)})", "", v)


# a closing signature: "Very respectfully, Pat Example, P.G. Hydrogeologist" (an agency report's sign-off, 2026-11-04)
_CLOSING = r"(?i:very respectfully|respectfully yours|respectfully|sincerely yours|sincerely|best regards|kind regards|warm regards|regards|thank you|thanks|cordially)"
_SIGNED_NAME = r"(?:[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)*|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)*|[A-Z]\.)){1,3}"
CLOSING_NAME_RE = re.compile(rf"(\b{_CLOSING}[,.!]?\s*(?:\n|\r\n)?\s*){_SIGNED_NAME}(?=\s*(?:,|\.|\n|$|\s+(?:P\.?G\.?|P\.?E\.?|Ph\.?D\.?|M\.?S\.?|M\.?P\.?H\.?|CPM|REHS)\b))")


def scrub_names(v: str) -> str:
    """Staff names after "Inspector" / "Investigator", in "contact <Name> at", and in a closing signature
    ("Very respectfully, <Name>, P.G.") become [name removed]."""
    v = TITLE_NAME_RE.sub(r"\1\2[name removed]", v)
    v = CONTACT_NAME_RE.sub(r"\1\2[name removed]", v)
    return CLOSING_NAME_RE.sub(r"\1[name removed]", v)


def has_repo_path(v) -> bool:
    """A string that carries a path into this repository (a pipeline note, not source data)."""
    if not isinstance(v, str):
        return False
    for m in _REPO_PATH.finditer(v):
        t = m.group(0).rstrip(".,;:)")
        rest = t.split("/", 1)[1]
        if "/" in rest or re.search(r"\.[A-Za-z]{2,7}$", rest):
            return True
    return False


def split_path_notes(raw, _path: str = ""):
    """(raw without the strings that carry repository paths, {dotted path: removed string})."""
    notes = {}
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            p = f"{_path}.{k}" if _path else str(k)
            if has_repo_path(v):
                notes[p] = v
                continue
            out[k], sub = split_path_notes(v, p)
            notes.update(sub)
        return out, notes
    if isinstance(raw, list):
        out = []
        for i, v in enumerate(raw):
            p = f"{_path}[{i}]"
            if has_repo_path(v):
                notes[p] = v
                continue
            item, sub = split_path_notes(v, p)
            out.append(item)
            notes.update(sub)
        return out, notes
    return raw, notes


def path_notes_to_meta(records: list[dict], meta: dict) -> dict:
    """Pipeline notes that name repository files stay out of each record's raw (the public source
    record): they move to the events file's meta, meta["internal_notes"][event_id]. Returns meta."""
    for rec in records:
        rec["raw"], notes = split_path_notes(rec.get("raw") or {})
        if notes:
            meta.setdefault("internal_notes", {})[rec["event_id"]] = notes
    return meta


def strip_personal(rec):
    """Drop keys that look like they hold a person's name, email or phone (several feeds carry staff
    contact details: reporter, contact, inspector, investigator, signed_by, submitted_by_name ...),
    at every depth of nested dicts and lists, and scrub emails, phone numbers and staff names
    ("Inspector Eddy", "contact Jane Doe at") inside string values. Keeps everything else as the
    source gave it."""
    if isinstance(rec, dict):
        out = {}
        for k, v in rec.items():
            ks = str(k)
            if NAME_KEYS.search(ks) or (PERSONAL_KEYS.search(ks) and not KEEP_KEYS.search(ks)):
                continue
            out[k] = strip_personal(v)
        return out
    if isinstance(rec, list):
        return [strip_personal(v) for v in rec]
    if isinstance(rec, str):
        return scrub_text(rec)
    return rec


# Words that make a discharger name an operator's, never a person's: "Robert T Savely WRF", "Kelly Twp Muni Auth",
# "Martha Elementary" (operator names of the outfall registry that read like a person's name)
OPERATOR_WORDS = set("""wwtp wwtf wtp wtf wrf wrp wrrf wpcf wpcp pcf pcp stp awt potw pwa pwd twp township muni municipal
auth authority authorities district dist county city town village borough boro commission board department dept utility
utilities water sewer sewerage wastewater sanitary sanitation treatment plant facility facilities station system systems
works regional reclamation recovery pollution control services service co company corp corporation inc llc lp ltd assn
association hoa poa coop cooperative club estates apartments apts mhp mobile home homes school schools elementary middle
high college university academy ctr center centre correctional prison resort hotel motel inn hospital farm farms dairy
foundation fdation trust partners properties development wwsl wwt wwrf rwrf awtf awwtp wqtc wrc cso csos sso psd msd
mua mud sd ud wsa subdiv subd subdivision elem sch univ campground nursing ministries foods products mfg manufacturing
enterprises holdings group labs laboratories sons bros brothers sawmill rtb""".split())   # not surnames such as Park, Mills, Church, Camp, Lodge
NAME_REMOVED = "[name removed]"


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


# fields a record carries only when its source gives them (absent, not null, on every other record):
#   stretch  an advisory that names a stretch of a river by its two ends, each end with a public point:
#            {"water": name, "start": {name, lat, lon, basis, source, url}, "end": {...}}. build/reaches.py traces the
#            stretch from start to end (reach kind "advisory_stretch") and build/status.py colours only that stretch.
OPTIONAL_EVENT_FIELDS = {"stretch"}


def event(**f) -> dict:
    """An event record with every field present (docs/plan.md §3); validates the enumerations."""
    rec = {
        "event_id": None, "source_id": None, "source_record_id": None, "parent_event_id": None,
        "event_type": "unknown", "status": "unknown",
        "discharger_id": None, "discharger_name": None, "npdes_permit": None,
        "outfall_id": None, "outfall_name": None,
        "waterbody_text": None, "water_slugs": [], "water_match": "none",
        "lat": None, "lon": None, "coord_source": None, "coord_precision_m": None,
        "started_at": None, "ended_at": None, "time_precision": None,
        "reported_at": None, "published_at": None, "source_updated_at": None, "fetched_at": now_iso(),
        "material": None, "volume_gal": None, "volume_text": None, "estimate_flag": "unknown",
        "authority": None, "advice_text": None, "advice_window_hours": None, "advice_window_basis": None,
        "source_url": None, "raw": {}, "parse_error": None,
        "duplicate_of": None,   # event_id of the record this one duplicates (another source's copy); status skips it
    }
    unknown = set(f) - set(rec) - OPTIONAL_EVENT_FIELDS
    if unknown:
        raise ValueError(f"unknown event fields: {sorted(unknown)}")
    rec.update(f)
    if rec["event_type"] not in EVENT_TYPES:
        raise ValueError(f"bad event_type {rec['event_type']!r}")
    if rec["status"] not in STATUSES:
        raise ValueError(f"bad status {rec['status']!r}")
    if rec["event_id"] is None and rec["source_id"] and rec["source_record_id"] is not None:
        rec["event_id"] = f"{rec['source_id']}:{rec['source_record_id']}"
    if not rec["event_id"]:
        raise ValueError("event needs event_id or source_id + source_record_id")
    rec["raw"] = strip_personal(rec["raw"] or {})
    return scrub_discharger(rec)


def write_events(source_id: str, records: list[dict], ok: bool = True, error: str | None = None, meta: dict | None = None,
                 path: Path | None = None) -> Path:
    """Write data/build/events/<source>.json (or path). On failure (ok=False) keep the previous records and
    record the error, so a feed outage never empties a water's history."""
    path = Path(path) if path is not None else EVENTS_DIR / f"{source_id}.json"
    prev = read_json(path, {}) or {}
    if not ok:
        # the retained records keep the previous file's meta (coverage, registry ids and above all
        # distribution_discouraged); only fetch health changes. A caller's meta adds to it.
        records = prev.get("records", [])
        prev_meta = prev.get("meta") or {}
        meta = {**prev_meta, **(meta or {})}
        if prev_meta.get("distribution_discouraged"):
            meta["distribution_discouraged"] = True
    for r in records:           # a module may set discharger_name after common.event
        if isinstance(r, dict):
            scrub_discharger(r)
    out = {"source_id": source_id, "fetched_at": now_iso(), "ok": ok, "error": error,
           "last_ok_at": now_iso() if ok else prev.get("last_ok_at"), "meta": meta or {},
           "count": len(records), "records": records}
    write_json(path, out)
    return path


def end_after(start: datetime, dur, precision: str | None) -> tuple[datetime, str]:
    """(end, basis) of a start plus an elapsed duration, in the start's zone. The arithmetic is done in UTC, so an
    end across a clock change is the elapsed end (21:30 EST plus 31 days 10 h 30 min is 09:00 EDT, not 08:00). A
    start known only to the day gives the latest end it allows: the date of (that day's end plus the duration),
    precision day, so no clock time is invented and the caution window never ends early."""
    tz = start.tzinfo
    if precision in ("day", "month", "year"):
        latest = (start.astimezone(UTC) + timedelta(days=1) + dur).astimezone(tz)
        end = datetime(latest.year, latest.month, latest.day, tzinfo=tz)
        return end, ("the start is known only to the day: the end is the day of the latest end it allows (the start "
                     "day's end plus the duration), at day precision")
    return (start.astimezone(UTC) + dur).astimezone(tz), "start plus the elapsed duration"


VOLUME_RANGE = re.compile(r"\d\s*(?:-|\u2013|\u2014|to|and)\s*[<>~]?\s*\d")
VOLUME_BOUND = re.compile(r"(<|>|\u2264|\u2265|\bless than\b|\bmore than\b|\bgreater than\b|\bover\b|\bunder\b|"
                          r"\bup to\b|\bat least\b|\bat most\b|\bexceed|\bbelow\b|\babove\b|\bminimum\b|\bmaximum\b)")
VOLUME_RATE = re.compile(r"(per\s*(day|hour|minute|min|second|sec)\b|/\s*(day|d|hr|h|min|s)\b|\bmgd\b|\bgpm\b|\bgpd\b|\bcfs\b)")
VOLUME_NUM = re.compile(r"(?<![\w.])(-)?\s*(\d+(?:\.\d+)?(?:e[+-]?\d+)?)")


def parse_volume_gal(text) -> tuple[int | None, str]:
    """'35.5 MG', '1,200,000 gallons', '75236', '1e6 gallons' -> (gallons, estimate_flag). Anything
    that is not one unambiguous volume returns None and the caller keeps the text: ranges
    ('10,000-50,000', '10 to 50 million gallons', 'approximately 1-2 MG') and bounds ('<100', 'over
    300,000') -> (None, 'estimated'); rates ('80 mgd', '381 gpm') and negative numbers -> (None,
    'unknown'). Never turns a negative into a positive."""
    if text is None:
        return None, "unknown"
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return (int(text), "unknown") if text >= 0 and text == text else (None, "unknown")
    s = str(text).strip().lower().replace(",", "")
    if not s:
        return None, "unknown"
    if VOLUME_RANGE.search(s) or VOLUME_BOUND.search(s):
        return None, "estimated"
    if VOLUME_RATE.search(s):
        return None, "unknown"
    nums = VOLUME_NUM.findall(s)
    if not nums:
        return None, "unknown"
    sign, num = nums[0]
    if sign:
        return None, "unknown"
    try:
        v = float(num)
    except ValueError:
        return None, "unknown"
    if v != v or v in (float("inf"), float("-inf")):
        return None, "unknown"
    approx = bool(re.search(r"approx|\best\b|estimat|about|~|roughly|around", s))
    if re.search(r"\b(mg|million)\b|million gallons|\d\s*mg\b", s):
        return int(v * 1_000_000), "estimated"
    if re.search(r"\bthousand\b|\bkgal\b", s):
        return int(v * 1_000), "estimated" if approx else "unknown"
    return int(v), "estimated" if approx else "unknown"
