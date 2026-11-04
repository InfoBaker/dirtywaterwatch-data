"""Shared helpers for the DirtyWaterWatch pipeline. Run modules from pipeline/ (python -m ingest.x).

Conventions (docs/plan.md §3 and §5): one JSON events file per source in data/build/events/, raw
responses in data/raw/<source>/, personal fields stripped, nothing invented.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
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
PHONE_RE = re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]\d{4}(?![\w-])"
                      r"|(?<![\w-])\d{3}[.-]\d{4}(?![\w-])")
# Staff names inside free text: "Inspector Eddy", "Investigator Tom Watson", "contact Jane Doe at ...".
# A name is one to three capitalised words or initials (an optional Mr/Ms/Dr first); common words that
# follow these titles without being a name ("Inspector General", "Contact Tank at") are not taken.
_NAME = r"(?:(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+)?(?:[A-Z]\.|[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)*)(?:\s+(?:[A-Z]\.|[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)*)){0,2}"
_NOT_NAME = (r"(?!(?:The|A|An|And|Or|Of|On|At|In|To|For|From|With|By|Was|Were|Is|Are|Has|Had|Will|Would|General|"
             r"Report|Reports|Office|Department|Dept|Division|Service|Services|Unit|Team|Staff|Program)\b)")
_NOT_CONTACT = (r"(?!(?:Tank|Tanks|Chamber|Chambers|Basin|Basins|Time|Point|Customer|Customers|City|Town|Village|"
                r"Police|Fire|Public|Us|Our|Your|Information|Info|Center|Centre|Desk|Line|Phone|Email)\b)")
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
    """How general a registry file is; the lower rank wins a duplicate outfall: a regional file (outfalls-ne.json,
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
        for i, o in enumerate(rows):
            if not isinstance(o, dict):
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
    """Emails and phone numbers inside free text become [email removed] / [phone removed]; staff
    names after "Inspector" / "Investigator", and in "contact <Name> at", become [name removed]."""
    v = EMAIL_RE.sub("[email removed]", v)
    return scrub_names(PHONE_RE.sub("[phone removed]", v))


def scrub_names(v: str) -> str:
    """Staff names after "Inspector" / "Investigator", and in "contact <Name> at", become [name removed]."""
    v = TITLE_NAME_RE.sub(r"\1\2[name removed]", v)
    return CONTACT_NAME_RE.sub(r"\1\2[name removed]", v)


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
    unknown = set(f) - set(rec)
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
    return rec


def write_events(source_id: str, records: list[dict], ok: bool = True, error: str | None = None, meta: dict | None = None) -> Path:
    """Write data/build/events/<source>.json. On failure (ok=False) keep the previous records and
    record the error, so a feed outage never empties a water's history."""
    path = EVENTS_DIR / f"{source_id}.json"
    prev = read_json(path, {}) or {}
    if not ok:
        # the retained records keep the previous file's meta (coverage, registry ids and above all
        # distribution_discouraged); only fetch health changes. A caller's meta adds to it.
        records = prev.get("records", [])
        prev_meta = prev.get("meta") or {}
        meta = {**prev_meta, **(meta or {})}
        if prev_meta.get("distribution_discouraged"):
            meta["distribution_discouraged"] = True
    out = {"source_id": source_id, "fetched_at": now_iso(), "ok": ok, "error": error,
           "last_ok_at": now_iso() if ok else prev.get("last_ok_at"), "meta": meta or {},
           "count": len(records), "records": records}
    write_json(path, out)
    return path


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
