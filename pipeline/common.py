"""Shared helpers for the DirtyWaterWatch pipeline. Run modules from pipeline/ (python -m ingest.x).

Conventions (docs/plan.md §3 and §5): one JSON events file per source in data/build/events/, raw
responses in data/raw/<source>/, personal fields stripped, nothing invented.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
BUILD_DIR = DATA_DIR / "build"
EVENTS_DIR = BUILD_DIR / "events"
OUT_DIR = ROOT / "out"
SOURCES_DIR = DATA_DIR / "sources"

HEADERS = {"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org/contact/)"}
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


def gnis_num(x) -> int | None:
    """A GNIS feature id as a number, so '00597915' (NHD's eight-digit text) and 597915 (openboatlaunch's API, from
    Wikidata, no leading zeros) compare equal. None for no id or one that is not a number."""
    if x is None or isinstance(x, bool):
        return None
    try:
        n = int(str(x).strip())
    except ValueError:
        return None
    return n if n > 0 else None


def same_gnis(a, b) -> bool:
    """Two GNIS ids name the same feature: equal as numbers (gnis_num), or the same non-empty text."""
    if a in (None, "") or b in (None, ""):
        return False
    na, nb = gnis_num(a), gnis_num(b)
    return na == nb if na is not None and nb is not None else str(a).strip() == str(b).strip()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
    tmp.replace(path)


# The row lists of a large registry file (data/waters-nhd.json) that dumps_rows writes one row per line.
ROW_LIST_KEYS = ("waters", "targets", "skipped", "problems")


def dumps_rows(obj, row_keys=ROW_LIST_KEYS) -> str:
    """A JSON document laid out to stay small and still diff by record (data/waters-nhd.json, 2026-11-15: at indent=1
    every coordinate took its own line and the file passed GitHub's 100 MB limit). The top-level keys keep their order;
    each list under row_keys is written one row per line with compact separators; every other value (the header
    strings, stats) is written at indent=1 as before. ensure_ascii=False, default=str (as write_json); the same data
    gives the same bytes; the text ends with one newline. json.loads gives back exactly what json.loads of the
    indent=1 file gave. A value that is not a non-empty dict is written at indent=1 (with the newline)."""
    if not isinstance(obj, dict) or not obj:
        return json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n"
    parts = []
    for k, v in obj.items():
        # the key exactly as json.dumps writes it (True -> "true", None -> "null", 1.5 -> "1.5"; a tuple refused)
        key = json.dumps({k: 0}, ensure_ascii=False)[1:-4]
        if k in row_keys and isinstance(v, list):
            body = ("[\n" + ",\n".join("  " + json.dumps(x, separators=(",", ":"), ensure_ascii=False, default=str)
                                       for x in v) + "\n ]") if v else "[]"
        else:
            # indent=1 nested one level down (a string holds no raw newline: json escapes it)
            body = json.dumps(v, indent=1, ensure_ascii=False, default=str).replace("\n", "\n ")
        parts.append(f" {key}: {body}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def dumps_plants(doc: dict) -> str:
    """data/outfalls-plants-us.json's own layout (research/federal/build_plant_outfalls.py; ingest.outfall_waters
    write_plants): the header keys one per line, then cso_features_not_in_inventory and outfalls one row per line."""
    out = ["{\n"]
    for k, v in doc.items():
        if k not in ("outfalls", "cso_features_not_in_inventory"):
            out.append(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False) + ",\n")
    out.append('"cso_features_not_in_inventory": [\n' + ",\n".join(
        json.dumps(x, ensure_ascii=False) for x in doc.get("cso_features_not_in_inventory") or []) + "\n],\n")
    out.append('"outfalls": [\n' + ",\n".join(json.dumps(x, ensure_ascii=False) for x in doc["outfalls"]) + "\n]\n}\n")
    return "".join(out)


def write_rows_json(path: Path, obj, row_keys=ROW_LIST_KEYS) -> None:
    """write_json with the dumps_rows layout: every writer of data/waters-nhd.json goes through here."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dumps_rows(obj, row_keys))
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
OPTIONAL_EVENT_FIELDS = {"stretch", "sampled_at"}  # source sample date, never an advisory issue/lift time


def system_wide_advisory(ev: dict) -> bool:
    """An authority's system-wide advisory shown at each of its outfalls (raw.advisory_scope "system-wide": Louisville
    MSD's MSD-01 banner, ingest/ky_louisville_msd.py): an advisory, not a discharge report. It is never counted as a
    discharge, never matched as a duplicate, never a notice that holds back the rain caution, and counted once per
    water (raw.advisory_key) among the advisories (review 2026-11-08 P2-1, P2-2)."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    return raw.get("advisory_scope") == "system-wide"


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


# ---------------------------------------------------------------- errors fit to keep (security review 2026-11-17 #7)
# What a failure leaves in a saved or published file (an events file's error and the error fields of its meta, the
# feeds' health in out/sources.json and the waters' stale reasons, out/meta.json's problems, a module's state file)
# and in the hourly log: the pipeline's own words, the kind of exception, a fixed category and the host at most:
#   "page: HTTPError: HTTP 404 at www.example.gov", "ConnectionError: refused at gis.example.gov",
#   "ValueError: no features" (a message the pipeline raised itself keeps its words up to any quoted answer).
# Never a library's or a provider's own text, which can quote a full address with its query string, an account id
# or the answer's body. The categories: HTTP <code>, timeout, refused, dns, tls, reset, redirects, unreachable,
# not JSON, unreadable, missing file, denied, exit <code>, failed. inbox.category is the same rule for the inbox files.
PIPELINE_DIR = Path(__file__).resolve().parent
_OWN_CODE = (str(PIPELINE_DIR), str(ROOT / "scripts"))
_LIBRARY_PARTS = ("site-packages", "dist-packages", f"{Path('/')}lib{Path('/')}python")
_URL_RE = re.compile(r"(?i)\b(?:https?|ftp|s3|wss?)://[^\s'\"<>`]+")
_HOST_ARG_RE = re.compile(r"host='([A-Za-z0-9.-]{1,253})'")
_HOSTNAME_RE = re.compile(r"(?i)^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)*$")
# where a library's or a transport's own words begin (requests, urllib3, urllib, ssl, socket, json)
_LIBRARY_TEXT = re.compile(
    r"\b\d{3} (?:Client|Server) Error\b|HTTPS?ConnectionPool\(|\bMax retries exceeded\b|\bRead timed out\b|"
    r"\[Errno -?\d+\]|\[SSL[:\] ]|\bCaused by \w|<urllib3\.|\bConnection aborted\b|\bConnection broken\b|"
    r"\bNameResolutionError\b|\bFailed to (?:resolve|establish)\b|\bRemoteDisconnected\b|\bExceeded \d+ redirects\b|"
    r"\bExpecting (?:value|property name|',' delimiter|':' delimiter)\b|\bHTTP Error \d{3}\b|<urlopen error\b|"
    r"\bcertificate verify failed\b|\bNo such file or directory\b")
_TEXT_CATEGORIES = (
    (re.compile(r"\b(\d{3}) (?:Client|Server) Error\b|\bHTTP Error (\d{3})\b|\bHTTP (\d{3})\b|"
                r"\bstatus(?: code)?[ :=]+(\d{3})\b|\((\d{3})\) when calling\b"), None),
    (re.compile(r"(?i)timed? ?out\b|\btimeout\b"), "timeout"),
    (re.compile(r"(?i)connection refused|\[Errno (?:111|61|10061)\]|ECONNREFUSED"), "refused"),
    (re.compile(r"(?i)name ?resolution|failed to resolve|name or service not known|nodename nor servname|"
                r"getaddrinfo|\[Errno -?(?:2|3|5|8)\] (?:Name|nodename|Temporary)"), "dns"),
    (re.compile(r"(?i)\bssl\b|certificate|\[SSL"), "tls"),
    (re.compile(r"(?i)connection (?:reset|aborted)|connection broken|RemoteDisconnected|IncompleteRead|"
                r"ChunkedEncodingError|ProtocolError"), "reset"),
    (re.compile(r"(?i)redirects"), "redirects"),
    (re.compile(r"(?i)max retries|connection|unreachable|network is"), "unreachable"),
    (re.compile(r"\bExpecting (?:value|property name|',' delimiter|':' delimiter)\b|JSONDecodeError"), "not JSON"),
    (re.compile(r"(?i)no such file or directory|FileNotFoundError"), "missing file"),
    (re.compile(r"(?i)permission denied|AccessDenied|Forbidden"), "denied"),
)
# an answer quoted into a message: a JSON object or list, markup, a bytes literal, a long quoted string
_BODY_START = re.compile(r"[{]|\[\s*[{\['\"]|<[A-Za-z!/?]|\bb['\"]|(?<![^\s:(=,\[])['\"][^'\"\n]{41}")
_SECRET_PARAM = re.compile(r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|key|token|access_token|secret|password|passwd|"
                           r"signature|sig|auth|session(?:id)?)=)[^&\s'\";,)]+")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_HEX_ID = re.compile(r"(?i)(?<![0-9a-z])(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32,})"
                     r"(?![0-9a-z])")
_LONG_TOKEN = re.compile(r"(?<![\w/.-])[A-Za-z0-9_+/=-]{40,}(?![\w/.-])")
# the meta keys that hold failure text (a key such as "failed" or "permits_failed" holds ids or counts, which a run may
# read back, and is left alone; their text is made with error_text where it is written)
_ERRORISH_KEY = re.compile(r"(?i)^(?:errors?|exception|problems|last_error|unread|"
                           r"[a-z0-9]+(?:_[a-z0-9]+)*_(?:error|errors))$")
_CODE_IN_BODY = re.compile(r"""["']code["']\s*:\s*["']?(\d{3,5})\b""")
_EXC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,60}$")


def url_label(url) -> str:
    """A failed document's name for a message: the last part of its path (no query string), else its host."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(str(url))
    except ValueError:
        return "[address]"
    name = u.path.rstrip("/").rsplit("/", 1)[-1]
    return name or (u.hostname or "[address]")


def url_host(url) -> str | None:
    """The host of an address (no user, no port, no path), or None."""
    try:
        from urllib.parse import urlsplit
        h = urlsplit(str(url)).hostname
    except ValueError:
        return None
    return h if h and _HOSTNAME_RE.match(h) else None


def _account_values() -> list[tuple[str, str]]:
    import os
    out = []
    for env, mark in (("R2_S3_ENDPOINT", "[endpoint]"), ("CLOUDFLARE_ACCOUNT_ID", "[account]")):
        v = (os.environ.get(env) or "").strip().rstrip("/")
        if len(v) >= 8:
            out.append((v, mark))
    return out


def redact_secrets(text: str) -> str:
    """Account ids, the R2 endpoint, e-mail addresses, keys in key=value form, bearer tokens and long ids out of text
    (addresses are left to the caller)."""
    t = str(text)
    for v, mark in _account_values():
        t = t.replace(v, mark)
    t = EMAIL_RE.sub("[address]", t)
    t = _BEARER.sub(lambda m: f"{m.group(1)} [redacted]", t)
    t = _SECRET_PARAM.sub(lambda m: f"{m.group(1)}[redacted]", t)
    t = _HEX_ID.sub("[id]", t)
    return _LONG_TOKEN.sub("[id]", t)


def text_category(text) -> str:
    """The fixed category a failure's words name (HTTP <code>, timeout, refused, ...), else "failed"."""
    t = str(text or "")
    for rx, word in _TEXT_CATEGORIES:
        m = rx.search(t)
        if m:
            return word or f"HTTP {next(g for g in m.groups() if g)}"
    return "failed"


def _host_in_text(text: str) -> str | None:
    m = _URL_RE.search(text)
    if m:
        h = url_host(m.group(0))
        if h:
            return h
    m = _HOST_ARG_RE.search(text)
    return m.group(1) if m and _HOSTNAME_RE.match(m.group(1)) else None


def _tidy(text: str, limit: int) -> str:
    t = re.sub(r"\s+", " ", text).strip().rstrip(":;,-–— (").strip()
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def _body_end(t: str, s: int) -> int:
    """Where an answer quoted into a message from s ends: its closing bracket (double-quoted strings inside skipped),
    markup's ">", its closing quote; the end of the text when it is never closed."""
    c = t[s]
    if c in "{[":
        depth, in_str, j = 0, False, s
        while j < len(t):
            ch = t[j]
            if in_str:
                if ch == "\\":
                    j += 1
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return len(t)
    if c == "<":
        j = t.find(">", s + 1)
        return len(t) if j < 0 else j + 1
    if c == "b" and s + 1 < len(t) and t[s + 1] in "'\"":
        j = t.find(t[s + 1], s + 2)
        return len(t) if j < 0 else j + 1
    if c in "'\"":
        j = t.find(c, s + 1)
        return len(t) if j < 0 else j + 1
    return s + 1


def _body_spans(t: str) -> list[tuple[int, int]]:
    out, i = [], 0
    while True:
        m = _BODY_START.search(t, i)
        if not m:
            return out
        e = max(_body_end(t, m.start()), m.start() + 1)
        out.append((m.start(), e))
        i = e


def remove_bodies(text: str) -> str:
    """Every answer quoted into a message taken out whole (a JSON object or list, markup, a bytes literal, a long
    quoted string), up to its end, or to the end of the text when it is never closed. An object's numeric "code"
    stays, as " (code 403)": a refusal still reads as one (export/coverage.py)."""
    t, out, i = str(text), "", 0
    for s, e in _body_spans(t):
        out += t[i:s]
        code = _CODE_IN_BODY.search(t, s, e) if t[s] in "{[" else None
        if code:
            out = out.rstrip().rstrip(":").rstrip() + f" (code {code.group(1)}) "
        i = e
    return out + t[i:]


def clean_error_text(text, limit: int = 300) -> str:
    """One failure's words as they may be kept: up to where a library's or a transport's own text begins, which
    becomes its category and host; any quoted answer taken out (remove_bodies); addresses as their host; secrets,
    ids and the job's account id out of the whole result, host included."""
    t = str(text or "")[:max(limit, 300) * 4]       # the regular expressions below never see a whole body
    m = _LIBRARY_TEXT.search(t)
    tail = ""
    if m:
        host = _host_in_text(t)
        tail = text_category(t[m.start():])
        if tail == "failed":
            tail = text_category(t)
        if host:
            tail += f" at {host}"
        t = t[:m.start()]
    t = remove_bodies(t)
    t = _URL_RE.sub(lambda u: url_host(u.group(0)) or "[address]", t)
    t = _tidy(t, limit)
    if tail:
        t = f"{t}: {tail}" if t else tail
    return _tidy(redact_secrets(t), limit)


def _raised_in_own_code(e: BaseException) -> bool:
    """True when the exception was raised by this repository's code (its last frame is under pipeline/ or scripts/
    and not in an installed library), so its message is the pipeline's own words."""
    tb = e.__traceback__
    if tb is None:
        return True
    while tb.tb_next is not None:
        tb = tb.tb_next
    f = str(tb.tb_frame.f_code.co_filename)
    return f.startswith(_OWN_CODE) and not any(p in f for p in _LIBRARY_PARTS)


def error_category(e: BaseException) -> str:
    """The fixed category of an exception: an answer's HTTP status, the kind of a transport failure, else what kind of
    thing went wrong. Never the exception's own words."""
    resp = getattr(e, "response", None)
    code = getattr(resp, "status_code", None) if resp is not None else None
    if not isinstance(code, int):
        code = getattr(e, "code", None) if type(e).__name__ == "HTTPError" else None
    if isinstance(code, int) and 100 <= code <= 599:
        return f"HTTP {code}"
    names = {c.__name__ for c in type(e).__mro__}
    if names & {"Timeout", "TimeoutError", "TimeoutExpired", "ReadTimeout", "ConnectTimeout", "timeout"}:
        return "timeout"
    if "ConnectionRefusedError" in names:
        return "refused"
    if names & {"SSLError", "SSLCertVerificationError", "CertificateError"}:
        return "tls"
    if "TooManyRedirects" in names:
        return "redirects"
    if names & {"ConnectionResetError", "ConnectionAbortedError", "RemoteDisconnected", "ChunkedEncodingError",
                "IncompleteRead", "ProtocolError", "BrokenPipeError"}:
        return "reset"
    if names & {"gaierror", "NameResolutionError"}:
        return "dns"
    if names & {"ConnectionError", "URLError", "NewConnectionError", "MaxRetryError", "RequestException"}:
        c = text_category(str(e))
        return c if c in ("refused", "dns", "tls", "reset", "timeout", "redirects") else "unreachable"
    if "JSONDecodeError" in names:
        return "not JSON"
    if "CalledProcessError" in names and isinstance(getattr(e, "returncode", None), int):
        return f"exit {e.returncode}"
    if "FileNotFoundError" in names:
        return "missing file"
    if "PermissionError" in names:
        return "denied"
    if names & {"ValueError", "KeyError", "IndexError", "TypeError", "AttributeError", "LookupError",
                "UnicodeError", "BadZipFile", "ParseError", "ExpatError", "EOFError", "DecodeError"}:
        return "unreadable"
    return "failed"


def error_host(e: BaseException) -> str | None:
    """The host a failed request went to (its response's or request's address), or None."""
    for obj in (getattr(e, "response", None), getattr(e, "request", None)):
        u = getattr(obj, "url", None) if obj is not None else None
        if u:
            h = url_host(u)
            if h:
                return h
    u = getattr(e, "url", None) or getattr(e, "filename", None) if type(e).__name__ == "HTTPError" else None
    return url_host(u) if u else _host_in_text(str(e))


def error_detail(e: BaseException, limit: int = 300) -> str:
    """What may be kept and printed of a caught exception's message (in place of str(e)): for one this repository
    raised, its own words (clean_error_text); for a library's, a fixed category and the host ("HTTP 404 at host",
    "timeout at host", "not JSON")."""
    if _raised_in_own_code(e) and not _LIBRARY_TEXT.search(str(e)):
        return clean_error_text(str(e), limit) or error_category(e)
    cat = error_category(e)
    if cat == "failed":
        cat = text_category(str(e))
    host = error_host(e)
    return _tidy(redact_secrets(cat + (f" at {host}" if host else "")), limit)


def error_text(e: BaseException, limit: int = 300) -> str:
    """error_detail with the exception's kind first (in place of f"{type(e).__name__}: {e}"):
    "HTTPError: HTTP 404 at host", "ReadTimeout: timeout at host", "ValueError: no features"."""
    name = type(e).__name__ if _EXC_NAME.match(type(e).__name__) else "Error"
    return _tidy(f"{name}: {error_detail(e, limit)}", limit)


def answer_error(err) -> str:
    """An error a service put in its answer (ArcGIS's {"code": 400, "message": ...} and the like) as it may be kept:
    its numeric code, never its message."""
    c = err.get("code") if isinstance(err, dict) else None
    if isinstance(c, bool):
        c = None
    if isinstance(c, int) or (isinstance(c, str) and c.strip().isdigit()):
        return f"error code {int(c)}"
    return "error"


def public_error(value, limit: int = 1000):
    """An error as it may be saved or published (write_events, the feeds' health, meta.json's problems): an exception
    becomes error_text; a text keeps each part's own words (parts split at "; ") with library text, answers,
    addresses and secrets taken out (clean_error_text). None stays None; it is idempotent."""
    if value is None:
        return None
    if isinstance(value, BaseException):
        return error_text(value, limit)
    t = str(value)[:max(limit, 300) * 4]
    # split at "; " only outside a quoted answer, so a semicolon inside a body never makes a part of its own
    spans = _body_spans(t)
    cuts = [m for m in re.finditer(r";\s+", t) if not any(s <= m.start() < e for s, e in spans)]
    pieces, i = [], 0
    for m in cuts:
        pieces.append(t[i:m.start()])
        i = m.end()
    pieces.append(t[i:])
    parts = [clean_error_text(p, limit) for p in pieces]
    return _tidy("; ".join(p for p in parts if p), limit) or "failed"


def public_meta_errors(obj, _under: bool = False):
    """A copy of an events file's meta (or any state dict) whose error fields (error, errors, *_error, *_errors,
    problems, last_error, exception) hold only public_error text; every other field is left as it is (a source's own
    address in meta.url is a citation and stays whole)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            under = _under or bool(_ERRORISH_KEY.match(str(k)))
            key = k
            if under and isinstance(k, str) and _URL_RE.search(k):
                key = base = _URL_RE.sub(lambda u: url_host(u.group(0)) or "[address]", k)
                n = 1
                while key in out:                   # two addresses on one host stay two entries
                    n += 1
                    key = f"{base} ({n})"
            out[key] = public_meta_errors(v, under)
        return out
    if isinstance(obj, list):
        return [public_meta_errors(v, _under) for v in obj]
    if _under and isinstance(obj, str):
        return public_error(obj)
    return obj


def safe_traceback(e: BaseException) -> str:
    """A traceback fit for a public log: the frames (file, line, function, the code line) and error_text, never the
    exception's own words or a chained exception's."""
    import traceback
    return f"Traceback (most recent call last):\n{''.join(traceback.format_tb(e.__traceback__))}{error_text(e)}\n"


def _safe_excepthook(tp, value, tb) -> None:
    try:
        e = value if value is not None else tp()
        sys.stderr.write(safe_traceback(e.with_traceback(tb)))
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - the plain hook rather than nothing
        sys.__excepthook__(tp, value, tb)


def _safe_thread_hook(args) -> None:
    if args.exc_type is SystemExit:
        return
    _safe_excepthook(args.exc_type, args.exc_value, args.exc_traceback)


# On GitHub's runner (the logs are public) an exception no module caught prints safe_traceback (security review
# 2026-11-17 #7, Astra 2026-11-21 P1-4); a developer's run keeps Python's own traceback.
if os.environ.get("GITHUB_ACTIONS") == "true":
    import threading
    sys.excepthook = _safe_excepthook
    threading.excepthook = _safe_thread_hook


def write_events(source_id: str, records: list[dict], ok: bool = True, error: str | None = None, meta: dict | None = None,
                 path: Path | None = None, partial: bool = False) -> Path:
    """Write data/build/events/<source>.json (or path). On failure (ok=False) keep the previous records and
    record the error, so a feed outage never empties a water's history. partial=True (with ok=False): a run that read
    some items and failed others, whose records already carry the previous ones for what failed: the given records
    are written, health stays false and last_ok_at stays the previous one (wi_mmsd_storm_updates, Astra re-review
    2026-11-15 P1-5); the default is unchanged for every other caller."""
    path = Path(path) if path is not None else EVENTS_DIR / f"{source_id}.json"
    prev = read_json(path, {}) or {}
    if not ok:
        # the retained records keep the previous file's meta (coverage, registry ids and above all
        # distribution_discouraged); only fetch health changes. A caller's meta adds to it.
        if not partial:
            records = prev.get("records", [])
        prev_meta = prev.get("meta") or {}
        meta = {**prev_meta, **(meta or {})}
        if prev_meta.get("distribution_discouraged"):
            meta["distribution_discouraged"] = True
    for r in records:           # a module may set discharger_name after common.event
        if isinstance(r, dict):
            scrub_discharger(r)
    at = now_iso()
    if ok or partial:
        mark_unread_gaps(prev, records, at, listed_only=not ok)
    # the error and meta's error fields as they may be kept (public_error; security review 2026-11-17 #7): the file is
    # saved with the pipeline state, and the error reaches out/sources.json
    out = {"source_id": source_id, "fetched_at": at, "ok": ok, "error": public_error(error),
           "last_ok_at": at if ok else prev.get("last_ok_at"), "meta": public_meta_errors(meta or {}),
           "count": len(records), "records": records}
    # prev_ok_at: the successful read before last_ok_at, so the status build can tell whether a successful read came
    # after the one that last listed an advisory (no_ok_read_since; owner, 2026-11-16). Written only where it is
    # known: a file from before this field keeps none until its next successful read.
    # partial_at: the latest partial read since the last successful one; partial_before_ok_at: that of the reads
    # between prev_ok_at and last_ok_at, so a listing by a partial read is not taken for the successful read's (Astra
    # review 2026-11-16 P1-1)
    if ok:
        out["prev_ok_at"] = prev.get("last_ok_at")
        if prev.get("partial_at"):
            out["partial_before_ok_at"] = prev["partial_at"]
    else:
        for k in ("prev_ok_at", "partial_before_ok_at", "partial_at"):
            if k in prev:
                out[k] = prev[k]
        if partial:
            out["partial_at"] = at
    write_json(path, out)
    return path


# A read within this many minutes after the read that listed an advisory is that same run's write (an events file from
# before prev_ok_at was kept: no_ok_read_since)
SAME_READ_MINUTES = 30
UNREAD_GAP_DAYS = 14        # build/status.py CONFIRM_DAYS: an unread time shorter than this changes nothing


def _iso_time(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def no_ok_read_since(header: dict | None, listed) -> bool | None:
    """True when the feed whose events-file header this is (fetched_at, ok, last_ok_at, prev_ok_at) has had no
    successful read since the read at `listed` (an advisory's raw._last_seen_in_source); False when it has; None when
    the header cannot tell (no header, no successful read on file, no listing time). A partial read (write_events
    partial=True) and a failed one leave last_ok_at as it was, so neither counts as successful.
    With prev_ok_at (every successful write keeps the one before): the run that listed the advisory is the first
    successful write at or after `listed`; a second one means a later read succeeded. Without it (a file written before
    the field): last_ok_at within SAME_READ_MINUTES of the listing is that listing run's own write."""
    if not isinstance(header, dict):
        return None
    seen, last_ok = _iso_time(listed), _iso_time(header.get("last_ok_at"))
    if seen is None or last_ok is None:
        return None
    if last_ok < seen:
        return True             # listed by a read that was not a successful one (a partial read), none since
    if "prev_ok_at" in header:
        prev_ok = _iso_time(header.get("prev_ok_at"))
        if prev_ok is not None and prev_ok >= seen:
            return False
        # one successful write at or after the listing: it is the listing run's own unless a partial read listed it
        # first (partial_before_ok_at: the latest partial read before that write)
        partial = _iso_time(header.get("partial_before_ok_at"))
        return not (partial is not None and partial >= seen)
    return last_ok <= seen + timedelta(minutes=SAME_READ_MINUTES)


def mark_unread_gaps(prev: dict, records: list, at: str, listed_only: bool = False) -> None:
    """At a successful read (write_events ok=True), raw._unread_gaps on each carried advisory whose source could not be
    read for more than UNREAD_GAP_DAYS after the read that last listed it: {"from": that read, "to": the read that lists
    it again, or this read when it no longer lists it}. The status build shows that time as end not confirmed, never as
    the authority's window after the fact (owner, 2026-11-16). Earlier gaps are carried from the previous file. A record
    with no gap is not touched; nor is a system-wide advisory (its own 48-hour rule). listed_only (a partial read):
    only a record the read lists again, since a partial read that does not show it is no evidence."""
    olds = {r.get("event_id"): r for r in (prev.get("records") or []) if isinstance(r, dict) and r.get("event_id")}
    if not olds:
        return
    now = _iso_time(at)
    for r in records:
        raw = r.get("raw") if isinstance(r, dict) else None
        p = olds.get(r.get("event_id")) if isinstance(raw, dict) else None
        if p is None or system_wide_advisory(r):
            continue
        praw = p.get("raw") if isinstance(p.get("raw"), dict) else {}
        gaps = [g for g in (praw.get("_unread_gaps") or []) if isinstance(g, dict)]
        for g in raw.get("_unread_gaps") or []:
            if isinstance(g, dict) and g not in gaps:
                gaps.append(g)
        old, new = praw.get("_last_seen_in_source"), raw.get("_last_seen_in_source")
        t_old, t_new = _iso_time(old), _iso_time(new)
        if t_old is not None and no_ok_read_since(prev, old) is True:
            to = new if t_new is not None and t_new > t_old else at       # listed again, or not listed at this read
            if listed_only and to != new:
                to = None
            t_to = _iso_time(to)
            if t_to is not None and now is not None and t_to - t_old > timedelta(days=UNREAD_GAP_DAYS) \
                    and not any(g.get("from") == old for g in gaps):
                gaps.append({"from": old, "to": to, "listed_again": to == new})
        if gaps:
            raw["_unread_gaps"] = gaps


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
