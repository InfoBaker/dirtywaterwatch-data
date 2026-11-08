"""The declarative field map of a generic ingester (docs/generic-ingesters.md): from one source row to the
event record of docs/plan.md §3. Not a feed; the runner is `python -m ingest.generic <source-id>`.

A `fetch` block in data/sources/<id>.yaml names the platform and endpoint, the safe fields (everything else is
dropped before anything is mapped or written to a record), the free-text fields the scrubbers run on, and
`record:`, one entry per event field. Each entry is a value spec:

  "FIELD"                                   the field's text (shorthand for {field: FIELD})
  {field: F}  or {field: [F1, F2]}          the first non-empty field; a fallback used is noted in raw._basis
  {const: X}                                a constant
  {template: "{F|filter|filter:arg}-..."}   a string built from row fields ({@started_at} reads a record field);
                                            empty when a field it names is empty, unless |default:x is given
  upper / lower / regex + replace / map + unmapped / parse / transform   applied in that order

Times (started_at, ended_at, reported_at, published_at, source_updated_at) take a time spec: {field, parse:
datetime | date | epoch_ms | epoch_s | epoch_ms_wallclock, formats, time (a separate time-of-day field),
precision, midnight: date | time (whether a value at exactly 00:00 is a date: by default text written as exact
midnight is a date and an epoch is a time; say midnight: date for a date-only field stored as an epoch)}; ended_at may instead be {duration: {days, hours, minutes}} (elapsed time after the start). Naive
times are read in the block's time_zone, which every block that reads times names. A time is never invented: what
the source does not give stays null, and a time outside 1990 to the day after the fetch is not used.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from common import (DATA_DIR, EVENT_TYPES, KEEP_KEYS, NAME_KEYS, NAME_REMOVED, PERSONAL_KEYS, STATUSES, end_after,
                    parse_volume_gal, read_json, scrub_discharger, scrub_text)

TIME_FIELDS = ("started_at", "ended_at", "reported_at", "published_at", "source_updated_at")
PRECISIONS = {"minute", "hour", "day", "month", "year", "poll"}
TIME_KINDS = {"datetime", "date", "epoch_ms", "epoch_s", "epoch_ms_wallclock"}
# record fields a value spec may fill (the runner owns event_id, source_id, fetched_at, raw and the water match)
VALUE_FIELDS = {"source_record_id", "parent_event_id", "discharger_id", "discharger_name", "npdes_permit", "outfall_id",
                "outfall_name", "waterbody_text", "coord_precision_m", "material", "authority", "advice_text",
                "advice_window_hours", "advice_window_basis", "source_url", "volume_text", "estimate_flag",
                "time_precision", "event_type", "status", "lat", "lon", "coord_source"}
SPECIAL_FIELDS = set(TIME_FIELDS) | {"volume"}
SPEC_KEYS = {"field", "const", "template", "upper", "lower", "regex", "replace", "map", "unmapped", "match", "parse",
             "transform", "formats", "time", "time_formats", "precision", "duration", "otherwise", "unit",
             "estimate", "text", "bare_number_text", "midnight"}
FILTERS = {"default", "clean", "upper", "lower", "slug", "address", "address_key", "num", "int", "compact", "strftime",
           "day"}
DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y")
DATETIME_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%y %H:%M", "%m/%d/%y %I:%M %p")
TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p", "%H%M")
# a date written with an exact midnight is a date (Socrata floating dates, CSV exports "11/01/2026 12:00:00 AM")
MIDNIGHT_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00(:00(\.0+)?)?$|[ T]0?0:00(:00(\.0+)?)?$|\s12:00(:00)?\s*AM$", re.I)
VOLUME_UNITS = {"gallons": 1, "gal": 1, "mg": 1_000_000, "million_gallons": 1_000_000, "liters": 0.264172,
                "m3": 264.172}
EARLIEST = datetime(1990, 1, 1, tzinfo=UTC)
FUTURE_END_TOLERANCE = timedelta(hours=1)
TIME_BASIS = {
    "epoch_ms_wallclock": "The source stores local wall-clock time as if it were UTC: each epoch value is read as UTC "
                          "and the wall-clock time labelled {tz}.",
    "epoch_ms": "Epoch milliseconds (UTC), shown in {tz}.",
    "epoch_s": "Epoch seconds (UTC), shown in {tz}.",
    "datetime": "Local times as the source writes them, read in {tz} unless they carry an offset.",
    "date": "Dates as the source writes them, in {tz}, at day precision.",
}
# the receiving-water text that names no surface water (kept as text, placed on no water)
NO_WATER = re.compile(r"^\s*(n\s*/?\s*a|none|no|unknown|unk|null|nil|tbd|-+|0|ground|groundwater|ground water|"
                      r"the ground|on the ground|ground surface|grass|soil|land|storm ?drains?|storm ?sewer|"
                      r"storm ?drain system|side ditch|ditch)\s*[.!]*\s*$", re.I)
NOT_REACHED = re.compile(r"\b(did not|didn'?t|does not|doesn'?t|never|no discharge)\s+(enter|reach|go)", re.I)
# a person named after an honorific in free text, in any case ("MR. SURNAME" in a capitalised GIS field);
# "Dr" is left out (in addresses it is Drive)
HONORIFIC = re.compile(r"\b(?i:Mr|Mrs|Ms|Mx|Miss)\.?\s+[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)?")
REDACTED = "[name removed]"
# field names that can hold a private person (beyond common.strip_personal's rule): a review is required
PERSONAL_FIELD = re.compile(r"(?:^|[_\s.-])name$|^name|owner|caller|resident|complain|report(?:ed)?[_\s-]?by|"
                            r"submit|homeowner|tenant|occupant|witness|author", re.I)
ADDR_WORDS = {"street": "st", "str": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr", "lane": "ln",
              "court": "ct", "place": "pl", "boulevard": "blvd", "parkway": "pkwy", "highway": "hwy", "terrace": "ter",
              "circle": "cir", "square": "sq", "turnpike": "tpke", "east": "e", "west": "w", "north": "n",
              "south": "s", "mount": "mt", "saint": "st", "route": "rt", "rte": "rt", "pike": "pk", "trail": "trl"}
TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")
# the modules a block may name a hook from: they hold registered functions only (no side effects on import)
HOOK_MODULE = re.compile(r"^ingest\.(?:generic\.transforms|[a-z]{2}_transforms)$")


class SpecError(ValueError):
    """A fetch block that cannot be run as written."""


@dataclass
class Ctx:
    """What a record is built with: the block, the run's times, and notes the field map leaves for raw."""
    source_id: str
    block: dict
    tz: ZoneInfo
    fetched_at: str
    source_updated_at: str | None = None
    extra: dict = field(default_factory=dict)       # platform metadata, transform caches

    @property
    def fetched_dt(self) -> datetime:
        return datetime.fromisoformat(self.fetched_at.replace("Z", "+00:00"))


# ---------------------------------------------------------------- small helpers

def clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).replace("\xa0", " ").split())


def slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(s).lower()).strip("-")


def norm_addr(s, for_match: bool = False) -> str:
    """A street address as a key: lower case, punctuation dropped, street words abbreviated. for_match also drops a
    source's "(duplicate)" mark and a " - suffix" ("428 E Preston St - SSO Site #72" -> "428 e preston st")."""
    t = clean(s).lower()
    if for_match:
        t = re.sub(r"\(\s*duplicate\s*\)|\bduplicate\b", " ", t)
        t = re.sub(r"\s+-\s+.*$", "", t)
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(ADDR_WORDS.get(w, w) for w in t.split())


def get(row: dict, path: str):
    """A field of the row; a dotted path reads nested objects ("geometry.x", "properties.name") when the row
    has no key with the dots in it."""
    if path in row:
        return row[path]
    cur = row
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def listify(v) -> list:
    return [] if v is None else list(v) if isinstance(v, (list, tuple)) else [v]


def hook(fn):
    """Register a function a fetch block may name (transform, post, waters.matcher, a spec's transform)."""
    fn._dww_hook = True
    return fn


def resolve(dotted: str):
    """A registered hook named by its dotted path ("ingest.generic.transforms.md_mde_record"). Only the hook modules
    (ingest.generic.transforms, ingest.<st>_transforms) are imported, and only functions marked @hook are returned."""
    mod, _, name = str(dotted).rpartition(".")
    if not mod or not HOOK_MODULE.match(mod):
        raise SpecError(f"hook {dotted!r} is not in ingest.generic.transforms or an ingest.<st>_transforms module")
    if importlib.util.find_spec(mod) is None:
        raise SpecError(f"hook module {mod!r} does not exist")
    fn = getattr(importlib.import_module(mod), name, None)
    if not callable(fn) or not getattr(fn, "_dww_hook", False):
        raise SpecError(f"hook {dotted!r} is not a registered hook function")
    return fn


def fnum(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = clean(v).replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def fmt_num(v) -> str:
    """672000.07 -> '672,000.07'; 10.0 -> '10'."""
    f = fnum(v)
    if f is None:
        return clean(v)
    return f"{f:,.2f}".rstrip("0").rstrip(".")


def row_sha(row: dict, ignore=()) -> str:
    return hashlib.sha1(json.dumps({k: v for k, v in row.items() if k not in ignore}, sort_keys=True,
                                   default=str).encode()).hexdigest()


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def scrub(text):
    """Emails, phone numbers, staff titles and names after an honorific removed from free text."""
    return scrub_people(scrub_text(text)) if isinstance(text, str) else text


# ---------------------------------------------------------------- templates

def _filter(v, name: str, arg: str | None, ctx: Ctx | None):
    if name == "default":
        return v if clean(v[0] if isinstance(v, tuple) else v) else arg
    if v is None or (isinstance(v, str) and not clean(v)):
        return v
    if name == "clean":
        return clean(v)
    if name == "upper":
        return clean(v).upper()
    if name == "lower":
        return clean(v).lower()
    if name == "slug":
        return slug(v)
    if name == "address":
        return norm_addr(v)
    if name == "address_key":
        return norm_addr(v, for_match=True)
    if name == "num":
        return fmt_num(v)
    if name == "int":
        f = fnum(v)
        return str(int(f)) if f is not None else clean(v)
    dt, prec = v if isinstance(v, tuple) else (v, None)
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return clean(dt)
    if not isinstance(dt, datetime):
        return clean(dt)
    if name == "compact":           # a time as a key: 20260523T0205 at minute precision, 20260523 at day
        return dt.strftime("%Y%m%d") + (dt.strftime("T%H%M") if prec not in ("day", "month", "year") else "")
    if name == "day":
        return dt.strftime("%Y-%m-%d")
    if name == "strftime":
        return dt.strftime(arg or "%Y-%m-%d")
    raise SpecError(f"unknown template filter {name!r}")


def render(template: str, row: dict, rec: dict | None, ctx: Ctx | None) -> str | None:
    """'{npdes_no|upper|slug|default:none}-{@started_at|compact}' -> text, or None when a field it names is empty
    and has no default. {@x} reads the record field x being built (a time with its precision for |compact)."""
    empty = False

    def sub(m):
        nonlocal empty
        name, *filters = [p.strip() for p in m.group(1).split("|")]
        if name.startswith("@"):
            f = name[1:]
            v = (rec or {}).get(f)
            if f in TIME_FIELDS and v is not None:
                v = (v, (rec or {}).get("time_precision"))
        else:
            v = get(row, name)
        for flt in filters:
            fname, _, arg = flt.partition(":")
            v = _filter(v, fname, arg if _ else None, ctx)
        if isinstance(v, tuple):
            v = v[0]
        if v is None or not clean(v):
            empty = True
            return ""
        return clean(v)

    out = TEMPLATE_RE.sub(sub, template)
    return None if empty else out


def template_parts(template: str) -> list[tuple[str, list[str]]]:
    out = []
    for m in TEMPLATE_RE.finditer(template or ""):
        p = [x.strip() for x in m.group(1).split("|")]
        out.append((p[0], p[1:]))
    return out


def template_fields(template: str) -> list[str]:
    return [n for n, _ in template_parts(template) if not n.startswith("@")]


# ---------------------------------------------------------------- value specs

def norm_spec(spec):
    if isinstance(spec, str):
        return {"field": spec}
    if isinstance(spec, dict):
        return spec
    return {"const": spec}


def lookup(spec: dict, row: dict) -> tuple[object, str | None]:
    """(the value, the field it came from) for a spec's field or fields (first non-empty)."""
    fields = spec.get("field")
    if fields is None:
        return None, None
    for f in ([fields] if isinstance(fields, str) else fields):
        v = get(row, f)
        if v is not None and clean(v) != "":
            return v, f
    return None, None


def apply_map(v, spec: dict):
    """The value map: keys compared after clean and case-folding (match: regex compares each key as a pattern,
    first match wins); unmapped: keep (the default), null, or a literal."""
    m = spec.get("map")
    if m is None:
        return v, True
    key = clean(v).casefold()
    if spec.get("match") == "regex":
        for pat, out in m.items():
            if re.search(str(pat), clean(v), re.I):
                return out, True
    else:
        for k, out in m.items():
            if clean(k).casefold() == key:
                return out, True
    un = spec.get("unmapped", "keep")
    if un == "keep":
        return v, False
    return (None if un in (None, "null") else un), False


def value(spec, row: dict, rec: dict | None, ctx: Ctx | None, notes: dict | None = None, target: str = ""):
    spec = norm_spec(spec)
    if "const" in spec:
        v = spec["const"]
    elif "template" in spec:
        v = render(spec["template"], row, rec, ctx)
    else:
        v, used = lookup(spec, row)
        fields = spec.get("field")
        if notes is not None and used and isinstance(fields, list) and used != fields[0]:
            notes.setdefault("_basis", {})[target] = f"{used} (the first of {', '.join(fields)} with a value)"
    if isinstance(v, str):
        v = clean(v)
        if spec.get("upper"):
            v = v.upper()
        if spec.get("lower"):
            v = v.lower()
        if spec.get("regex") and v:
            m = re.search(spec["regex"], v, re.I)
            v = (m.expand(spec["replace"]) if spec.get("replace") else m.group(0)) if m else None
    if v is not None and v != "" and "map" in spec:
        v, hit = apply_map(v, spec)
        if not hit and notes is not None and spec.get("unmapped", "keep") != "keep":
            notes.setdefault("_unmapped", {})[target] = True
    parse = spec.get("parse")
    if parse in ("number", "float"):
        v = fnum(v)
    elif parse == "int":
        f = fnum(v)
        v = int(round(f)) if f is not None else None
    elif parse == "text" and v is not None:
        v = clean(v) or None
    if spec.get("transform"):
        v = resolve(spec["transform"])(v, row, ctx)
    if isinstance(v, str) and v == "":
        v = None
    return v


# ---------------------------------------------------------------- times

def _localize(dt: datetime, tz: ZoneInfo) -> datetime:
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt


def wall_note(dt: datetime) -> str | None:
    """A note when a local wall-clock time is ambiguous (the hour repeated at fall-back: the first is used) or does
    not exist (the hour skipped at spring-forward)."""
    if dt is None or not isinstance(dt.tzinfo, ZoneInfo):
        return None
    a, b = dt.replace(fold=0), dt.replace(fold=1)
    if a.utcoffset() == b.utcoffset():
        return None
    back = a.astimezone(UTC).astimezone(dt.tzinfo).replace(tzinfo=None)
    if back != a.replace(tzinfo=None):
        return f"{a.replace(tzinfo=None).isoformat()} does not exist in {dt.tzinfo.key} (the clock skipped that hour)"
    return (f"{a.replace(tzinfo=None).isoformat()} happened twice in {dt.tzinfo.key} (the clock went back): read as "
            f"the first, {a.isoformat()}")


def parse_datetime(v, tz: ZoneInfo, formats=None, midnight: str | None = None) -> tuple[datetime | None, str | None]:
    """(aware datetime, precision) from a source's text: the block's formats, else ISO 8601, RFC 2822 (RSS) and the
    common US forms. A date with no time of day, or a naive one written as exact midnight ("2026-11-01T00:00:00.000",
    "11/01/2026 12:00:00 AM"), is precision day, unless midnight is "time" (a field that holds times)."""
    s = clean(v)
    if not s:
        return None, None
    midnight = midnight != "time" and bool(MIDNIGHT_TEXT.search(s))
    for fmt in formats or ():
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        timed = any(c in fmt for c in ("%H", "%I", "%M"))
        return _localize(dt, tz), ("minute" if timed and not (midnight and dt.tzinfo is None) else "day")
    if formats:
        return None, None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=tz), "day"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is not None:
        if dt.tzinfo is None and midnight:
            return dt.replace(tzinfo=tz), "day"
        return _localize(dt, tz), "minute"
    if re.search(r"[A-Za-z]{3},?\s+\d|\d{1,2}\s+[A-Za-z]{3}\s+\d{4}", s):
        try:
            dt = parsedate_to_datetime(s)
            if dt is not None:
                return _localize(dt, tz), "minute"
        except (TypeError, ValueError):
            pass
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return _localize(dt, tz), ("day" if midnight else "minute")
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(tzinfo=tz), "day"
        except ValueError:
            pass
    return None, None


def parse_clock(v, formats=None) -> time | None:
    s = clean(v)
    if not s:
        return None
    for fmt in formats or TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def parse_epoch(v, kind: str, tz: ZoneInfo, midnight: str | None = None) -> tuple[datetime | None, str | None]:
    """(datetime, precision). An epoch is a time, also at 00:00 (an overflow can end at midnight). With midnight
    "date" (a date-only field stored as an epoch), one at exactly midnight (UTC midnight for epoch_ms / epoch_s,
    wall midnight for epoch_ms_wallclock) is the date as written, precision day."""
    f = fnum(v)
    if f is None:
        return None, None
    try:
        t = datetime.fromtimestamp(f / (1000 if kind != "epoch_s" else 1), UTC)
    except (OverflowError, OSError, ValueError):
        return None, None
    if midnight == "date" and (t.hour, t.minute, t.second, t.microsecond) == (0, 0, 0, 0):
        return datetime(t.year, t.month, t.day, tzinfo=tz), "day"
    if kind == "epoch_ms_wallclock":     # local wall-clock time stored as if it were UTC (common on ArcGIS layers)
        return t.replace(tzinfo=None).replace(tzinfo=tz), "minute"
    return t.astimezone(tz), "minute"


def time_value(spec, row: dict, rec: dict, ctx: Ctx, notes: dict, target: str) -> tuple[datetime | None, str | None]:
    """(aware datetime, precision) for one time field of the record."""
    spec = norm_spec(spec)
    if "duration" in spec:
        start = rec.get("_start_dt")
        dur = duration(spec["duration"], row)
        if start is None or dur is None:
            return None, None
        end, basis = end_after(start, dur, rec.get("time_precision"))
        notes.setdefault("_basis", {})[target] = basis + " (" + ", ".join(
            f"{k} {v}" for k, v in spec["duration"].items()) + ")"
        return end, rec.get("time_precision")
    if "const" in spec:
        return parse_datetime(spec["const"], ctx.tz, midnight=spec.get("midnight"))
    v, used = lookup(spec, row)
    fields = spec.get("field")
    if used and isinstance(fields, list) and used != fields[0]:
        notes.setdefault("_basis", {})[target] = f"{used} (the first of {', '.join(fields)} with a value)"
    kind = spec.get("parse", "datetime")
    if v is None:
        return None, None
    notes.setdefault("_time_kinds", set()).add(kind)
    if kind in ("epoch_ms", "epoch_s", "epoch_ms_wallclock"):
        dt, prec = parse_epoch(v, kind, ctx.tz, spec.get("midnight"))
    elif kind == "date":
        dt, prec = parse_datetime(v, ctx.tz, spec.get("formats"))
        if dt is not None:
            dt, prec = datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo), "day"
    else:
        dt, prec = parse_datetime(v, ctx.tz, spec.get("formats"), spec.get("midnight"))
    if dt is None:
        notes.setdefault("_problems", []).append(f"unreadable {used} {clean(v)!r}")
        return None, None
    if spec.get("time"):                     # a separate time-of-day field: the date part is the day
        t = parse_clock(get(row, spec["time"]), spec.get("time_formats"))
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo)
        prec = "day"
        if t is not None:
            dt, prec = dt.replace(hour=t.hour, minute=t.minute), "minute"
    if spec.get("precision"):
        prec = spec["precision"]
    if kind in ("datetime", "epoch_ms_wallclock") and prec not in ("day", "month", "year"):
        w = wall_note(dt)
        if w:
            notes.setdefault("_time_notes", {})[target] = w
    # sanity: no source time before 1990 or after the day after the fetch (epoch units, typed years); an end may lie
    # in the future (a planned lift), which is handled with the status
    u = dt.astimezone(UTC)
    if u < EARLIEST or (target != "ended_at" and u > ctx.fetched_dt + timedelta(days=1)):
        notes.setdefault("_problems", []).append(f"{used} {clean(v)!r} reads as {dt.isoformat()}, outside 1990 to the "
                                                 f"day after the fetch: not used")
        notes.setdefault("_unused_times", {})[target] = dt.isoformat()
        return None, None
    return dt, prec


def duration(spec: dict, row: dict) -> timedelta | None:
    """The source's elapsed duration: {days: F, hours: F, minutes: F} (any of them); None when none is given, one
    is not a number or one is negative."""
    parts = {k: clean(get(row, f)) for k, f in spec.items() if k in ("days", "hours", "minutes", "seconds")}
    if not any(parts.values()):
        return None
    try:
        vals = {k: float(v) if v else 0.0 for k, v in parts.items()}
    except ValueError:
        return None
    if min(vals.values()) < 0 or not all(math.isfinite(x) for x in vals.values()):
        return None
    return timedelta(**vals)


# ---------------------------------------------------------------- privacy

@lru_cache(maxsize=1)
def _allowlist() -> frozenset:
    d = read_json(DATA_DIR / "name-allowlist.json", {}) or {}
    return frozenset(" ".join(re.sub(r"[^a-z0-9]+", " ", str(x).lower()).split()) for x in d.get("names", []))


def scrub_people(text: str, allow=None) -> str:
    """Names after an honorific -> [name removed] (allowlisted phrases such as "Mr. Rooter" stay)."""
    if not text:
        return text
    allow = _allowlist() if allow is None else allow

    def rep(m):
        return m.group(0) if " ".join(re.sub(r"[^a-z0-9]+", " ", m.group(0).lower()).split()) in allow else REDACTED
    return HONORIFIC.sub(rep, text)


def personal_field(name: str) -> bool:
    """A field path any part of which looks like it holds a private person: a name, owner, caller, resident,
    complainant, reporter or submitter, an email or a phone (common.strip_personal's rule and more)."""
    for part in str(name).split("."):
        if NAME_KEYS.search(part) or (PERSONAL_KEYS.search(part) and not KEEP_KEYS.search(part)) \
                or PERSONAL_FIELD.search(part):
            return True
    return False


def safe_row(row: dict, block: dict) -> tuple[dict, list[str]]:
    """(only the safe fields, the safe fields dropped because their value is an object or a list). A dotted safe
    field keeps that nested leaf under its dotted name; an object is never kept whole (its keys were not reviewed).
    Free-text fields are scrubbed (emails, phones, staff titles, names after an honorific)."""
    out, dropped = {}, []
    for f in block["safe_fields"]:
        v = row[f] if f in row else get(row, f)
        if isinstance(v, (dict, list)):
            dropped.append(f)
            continue
        if f in row or v is not None:
            out[f] = v
    strict = block.get("free_text_scrub") == "strict"
    for f in block.get("free_text") or ():
        if isinstance(out.get(f), str):
            out[f] = scrub_strict(out[f]) if strict else scrub(out[f])
    # round_coords: a reporter's point (a bloom seen from a home) kept only to this many decimals, in the record's
    # raw.row and in data/raw alike (opt-in per block; review 2026-11-08 TN P2-3)
    nd = block.get("round_coords")
    if nd is not None:
        for f in ("_x", "_y"):
            if isinstance(out.get(f), (int, float)):
                out[f] = round(float(out[f]), int(nd))
    # operator_fields: a permittee or facility name that reads as only a person's (a small private system filed under
    # its owner) is removed before anything is saved or mapped (common.scrub_discharger); opt-in per block
    for f in block.get("operator_fields") or ():
        if isinstance(out.get(f), str) and out[f].strip():
            if scrub_discharger({"discharger_name": out[f]})["discharger_name"] == NAME_REMOVED:
                out[f] = NAME_REMOVED
    return out, dropped


# strict scrub (review 2026-11-07 TX P1-1): numbers that are not house numbers, kept through the cut; a number after a
# slash or at the start of a field is a house number like any other ("Line Break/1967 Columbus Ave.")
ROAD_NUMBER = re.compile(r"\b(?:FM|RM|CR|SH|IH|HWY|US|SPUR|LOOP|PR|BUS|I|STATE\s+HIGHWAY|COUNTY\s+ROAD|FARM\s+TO\s+MARKET|"
                         r"RANCH\s+ROAD|INTERSTATE|HIGHWAY|ROUTE|RT|SR)[\s.-]{0,3}\d{1,4}[A-Z]?\b", re.I)
SEGMENT_BEFORE_WATER = re.compile(
    r"(?:^\s*|\bseg(?:ment)?\.?\s*(?:no\.?|#)?\s*)\d{3,4}[A-Z]{0,2}(?=\s+(?:of\s+the\s+)?(?:[A-Za-z'.]+\s+){0,4}?"
    r"(?:creek|river|bayou|arroyo|lake|bay|reservoir|channel|tidal|basin|segment|estuary|lagoon|laguna)\b)", re.I)
STREET_AHEAD = re.compile(r"^\W*(?:\S+\s+){0,7}?(?:street|st|road|rd|drive|dr|lane|ln|avenue|ave|blvd|boulevard|way|court|"
                          r"ct|circle|cir|trail|trl|parkway|pkwy|bend|crossing|place|pl|loop|terrace|ter|cove|cv|path|"
                          r"highway|hwy|run)\b\.?", re.I)
STREET_HOUSE = re.compile(
    r"(?:(?<![\w.,/:#-])|(?<=#))(\d{1,6}[A-Za-z]?(?:-\d{1,6}[A-Za-z]?)*)(?=\s{1,2}(?:(?:block\s+of|at|on|in|of)\s{1,2})?"
    r"(?:[NSEW]\.?\s{0,2}){0,3}\s?(?:\d{1,3}(?:st|nd|rd|th)\b|(?:[A-Za-z][\w'.-]*\s{1,2}){1,3}(?:street|st|road|rd|drive|dr|lane|ln|avenue|ave|"
    r"blvd|boulevard|way|court|ct|circle|cir|trail|trl|parkway|pkwy|bend|crossing|place|pl|loop|terrace|ter|cove|cv|"
    r"path|run|trace|fwy|freeway|expy|expressway|pass|row|square|sq|plaza|walk|hollow|holw|ridge|glen|park|"
    r"Qzqx[a-z]+)\b|Qzqx[a-z]+))", re.I)
# a range of house numbers ("17613-17645-17661 Northern Harrier", "606-608 Port St") before a name is an address, street
# word or not
HOUSE_RANGE = re.compile(r"(?<![\w.,/:#-])\d{2,6}[A-Za-z]?(?:-\d{2,6}[A-Za-z]?)+(?=\s{1,2}(?:[NSEW]\.?\s{1,2})?[A-Z])")
UNIT_NUMBER = re.compile(r"\b(lot|apt|apartment|unit|suite|ste|space|spc|trailer|bldg|building)\.?\s*(?:no\.?|#)?\s*\d+[A-Za-z]?\b",
                         re.I)


def scrub_strict(text):
    """free_text_scrub: strict (a filer's free text that can carry residents' names and home addresses): scrub, then
    owners' and residents' names and every house number cut, as Michigan's filer text is (mi_egle_mienviro.free_text),
    with a number after a slash read as one at the start of a field, and lot, apartment and unit numbers cut. Road
    numbers ("FM 1960") and a segment number before a water ("2202 Arroyo Colorado Above Tidal") are not house
    numbers and stay."""
    if not isinstance(text, str):
        return text
    from ingest import mi_egle_mienviro as MI          # here: the module imports this one's neighbours
    keep: list[str] = []

    def hold(m):                      # a word-shaped stand-in, so "12345 FM 1960 Rd" still reads as an address
        keep.append(m.group(0))
        i, tag = len(keep) - 1, ""
        while True:
            tag = "abcdefghijklmnopqrstuvwxyz"[i % 26] + tag
            i = i // 26 - 1
            if i < 0:
                break
        return f"Qzqx{tag}"
    t = ROAD_NUMBER.sub(hold, text)
    t = SEGMENT_BEFORE_WATER.sub(lambda m: m.group(0) if STREET_AHEAD.match(t[m.end():]) else hold(m), t)
    t = re.sub(r"(?<=[A-Za-z.)])/(?=\s*\d)", "/ ", t)        # "Line Break/1967 ...", not a date "12/18/2024"
    t = UNIT_NUMBER.sub(lambda m: f"{m.group(1)} [house number removed]", t)
    t = scrub_people(MI.free_text(t))
    t = HOUSE_RANGE.sub("[house number removed]", t)
    t = STREET_HOUSE.sub(lambda m: m.group(0) if (m.start() and t[m.start() - 1] == "#" and len(m.group(1)) < 3)
                         else "[house number removed]", t)      # whatever stands before it ("No. 19", "LS 8015", "MH 11770 at")
    def back(m):
        i = 0
        for c in m.group(1):
            i = i * 26 + "abcdefghijklmnopqrstuvwxyz".index(c) + 1
        return keep[i - 1] if 0 < i <= len(keep) else m.group(0)
    t = re.sub(r"Qzqx([a-z]+)", back, t)
    return t


# ---------------------------------------------------------------- validation

def spec_fields(spec) -> list[str]:
    """The source fields a spec reads (to check them against the safe fields)."""
    spec = norm_spec(spec)
    out = []
    f = spec.get("field")
    if f:
        out += [f] if isinstance(f, str) else list(f)
    if spec.get("template"):
        out += template_fields(spec["template"])
    if spec.get("time"):
        out.append(spec["time"])
    if isinstance(spec.get("duration"), dict):
        out += [v for k, v in spec["duration"].items() if k in ("days", "hours", "minutes", "seconds")]
    if spec.get("text"):
        out += template_fields(spec["text"])
    return out


def _regex_errs(where: str, pat) -> list[str]:
    try:
        re.compile(str(pat))
        return []
    except re.error as e:
        return [f"{where}: bad regular expression {pat!r} ({e})"]


def spec_errors(where: str, spec, safe: list, target: str | None = None) -> list[str]:
    """Problems in one value or time spec."""
    errs = []
    s = norm_spec(spec)
    bad = set(s) - SPEC_KEYS
    if bad:
        errs.append(f"{where}: unknown keys {sorted(bad)}")
    for f in spec_fields(s):
        if f not in safe:
            errs.append(f"{where} reads {f!r}, which is not a safe field")
    for t in (s.get("template"), s.get("text")):
        for _, filters in template_parts(t or ""):
            for flt in filters:
                if flt.partition(":")[0] not in FILTERS:
                    errs.append(f"{where}: unknown template filter {flt!r}")
    if s.get("regex"):
        errs += _regex_errs(where, s["regex"])
    if isinstance(s.get("map"), dict):
        if any(isinstance(x, bool) or x is None for x in s["map"]):
            errs.append(f"{where}: a map key reads as true, false or null in YAML (Yes, No, On, Off, ~): quote it")
        if s.get("match") == "regex":
            for pat in s["map"]:
                errs += _regex_errs(where, pat)
    elif "map" in s:
        errs.append(f"{where}: map is a mapping")
    if s.get("match") not in (None, "exact", "regex"):
        errs.append(f"{where}: match is exact or regex")
    if s.get("parse") is not None and s["parse"] not in TIME_KINDS | {"number", "float", "int", "text"}:
        errs.append(f"{where}: unknown parse {s['parse']!r}")
    if target in TIME_FIELDS and s.get("parse") not in (None, *TIME_KINDS):
        errs.append(f"{where}: a time is parsed as one of {sorted(TIME_KINDS)}")
    if target is not None and target not in TIME_FIELDS and s.get("parse") in TIME_KINDS:
        errs.append(f"{where}: parse {s['parse']!r} is for times")
    if s.get("midnight") is not None and (s["midnight"] not in ("date", "time") or (target is not None and target
                                                                                   not in TIME_FIELDS)):
        errs.append(f"{where}: midnight is date or time, on a time field")
    if s.get("precision") is not None and s["precision"] not in PRECISIONS:
        errs.append(f"{where}: precision {s['precision']!r} is not one of {sorted(PRECISIONS)}")
    if "duration" in s and (target != "ended_at" or not isinstance(s["duration"], dict) or not s["duration"]
                            or set(s["duration"]) - {"days", "hours", "minutes", "seconds"}):
        errs.append(f"{where}: duration is {{days, hours, minutes, seconds}} and only for ended_at")
    if "unit" in s and str(s["unit"]).lower() not in VOLUME_UNITS:
        errs.append(f"{where}: unknown volume unit {s['unit']!r} (one of {sorted(VOLUME_UNITS)})")
    if s.get("estimate") not in (None, "estimated", "measured", "from_text"):
        errs.append(f"{where}: estimate is estimated, measured or from_text")
    if s.get("transform"):
        try:
            resolve(s["transform"])
        except SpecError as e:
            errs.append(f"{where}: {e}")
    return errs


def uses_local_times(block: dict) -> bool:
    """Whether the block reads a time whose zone the source does not state (text, dates, wall-clock epochs)."""
    specs = [v for k, v in (block.get("record") or {}).items() if k in TIME_FIELDS]
    snap = block.get("snapshot") if isinstance(block.get("snapshot"), dict) else {}
    if snap.get("poll_time"):
        specs.append(snap["poll_time"])
    if isinstance(block.get("decoded_times"), dict):
        specs.append({"parse": block["decoded_times"].get("parse", "datetime")})
    for s in specs:
        s = norm_spec(s)
        if "duration" not in s and s.get("parse", "datetime") in ("datetime", "date", "epoch_ms_wallclock"):
            return True
    return False


def water_state_module(st: str) -> str | None:
    """The state's water matcher module (ingest/<st>_waters.py with match_waters), or None."""
    from ingest.generic.transforms import WATER_MODULES
    name = WATER_MODULES.get(str(st).upper()) or f"ingest.{str(st).lower()}_waters"
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    try:            # read, not imported: the module must define match_waters
        return name if re.search(r"^def match_waters\(", open(spec.origin).read(), re.M) else None
    except OSError:
        return None


HISTORY_KEYS = {"keep_missing", "revisions", "track", "missing_key", "supersede", "confirm_while_listed"}


def validate(block: dict, source_id: str = "") -> list[str]:
    """Problems that stop a fetch block from running (an empty list when it can run). Nothing is fetched or
    written, and only the hook modules are imported."""
    errs = []
    if not isinstance(block, dict):
        return ["fetch is not a mapping"]
    if not block.get("platform"):
        errs.append("fetch.platform is missing")
    safe = block.get("safe_fields")
    if not isinstance(safe, list) or not safe or not all(isinstance(f, str) and f for f in safe):
        errs.append("fetch.safe_fields is missing: every block lists the fields it may keep")
        safe = [f for f in safe if isinstance(f, str)] if isinstance(safe, list) else []
    reviewed = block.get("reviewed_fields") or {}
    if not isinstance(reviewed, dict):
        errs.append("reviewed_fields is {field: reason}")
        reviewed = {}
    for f, why in reviewed.items():
        if not clean(why):
            errs.append(f"reviewed_fields.{f}: give the reason the field holds no private person")
    for f in safe:
        if personal_field(f) and f not in reviewed:
            errs.append(f"safe field {f!r} may hold a private person (a name, owner, caller, reporter, email or phone); "
                        f"list it under reviewed_fields with the reason it does not, or leave it out")
    rec = block.get("record") or {}
    if not isinstance(rec, dict) or "source_record_id" not in rec:
        errs.append("fetch.record.source_record_id is missing")
        rec = rec if isinstance(rec, dict) else {}
    for k, spec in rec.items():
        if k not in VALUE_FIELDS and k not in SPECIAL_FIELDS:
            errs.append(f"record.{k} is not an event field a block may fill")
            continue
        s = norm_spec(spec)
        errs += spec_errors(f"record.{k}", s, safe, k)
        if k == "event_type" and "const" in s and s["const"] not in EVENT_TYPES:
            errs.append(f"record.event_type {s['const']!r} is not an event type")
        if k == "event_type" and isinstance(s.get("map"), dict):
            for out in s["map"].values():
                if out not in EVENT_TYPES:
                    errs.append(f"record.event_type maps to {out!r}, not an event type")
        if k == "status":
            for out in (s.get("map") or {}).values() if isinstance(s.get("map"), dict) else ():
                if out not in STATUSES:
                    errs.append(f"record.status maps to {out!r}, not a status")
            if "const" in s and s["const"] not in STATUSES:
                errs.append(f"record.status {s['const']!r} is not a status")
            other = s.get("otherwise", "from_end")
            if other != "from_end" and other not in STATUSES:
                errs.append(f"record.status otherwise {other!r} is from_end or a status")
        if k == "time_precision" and "const" in s and s["const"] not in PRECISIONS:
            errs.append(f"record.time_precision {s['const']!r} is not a precision")
    for key, spec in (block.get("raw_notes") or {}).items():
        if not str(key).startswith("_"):
            errs.append(f"raw_notes.{key}: a note's name starts with _ (raw.row holds the source's fields)")
        errs += spec_errors(f"raw_notes.{key}", spec, safe)
    dts = block.get("decoded_times")
    if dts is not None:
        if not isinstance(dts, dict) or not isinstance(dts.get("fields"), list) or dts.get("parse", "datetime") not in TIME_KINDS:
            errs.append("decoded_times is {fields: [...], parse}")
        else:
            errs += [f"decoded_times reads {f!r}, which is not a safe field" for f in dts["fields"] if f not in safe]
    for f in block.get("free_text") or ():
        if f not in safe:
            errs.append(f"free_text field {f!r} is not a safe field")
    if block.get("free_text_scrub") not in (None, "strict"):
        errs.append("free_text_scrub is strict (or absent: the standard scrub)")
    if block.get("time_zone"):
        try:
            ZoneInfo(block["time_zone"])
        except Exception:  # noqa: BLE001
            errs.append(f"unknown time_zone {block['time_zone']!r}")
    elif uses_local_times(block):
        errs.append("time_zone is missing: name the zone the source's times are in (UTC when they are UTC)")
    w = block.get("waters") or {}
    if not isinstance(w, dict):
        errs.append("waters is a mapping")
        w = {}
    bad_w = set(w) - {"matcher", "state", "county", "county_field", "aliases", "no_water"}
    if bad_w:
        errs.append(f"waters: unknown keys {sorted(bad_w)}")
    hooks = [("transform", f) for f in listify(block.get("transform"))] + \
            [("post", f) for f in listify(block.get("post"))] + [("waters.matcher", f) for f in listify(w.get("matcher"))]
    for k, fn in hooks:
        try:
            resolve(fn)
        except SpecError as e:
            errs.append(f"{k}: {e}")
    if str(w.get("matcher") or "").endswith(".state_waters"):
        if not w.get("state"):
            errs.append("waters.state is missing: the state matcher needs the state")
        elif not water_state_module(w["state"]):
            errs.append(f"waters.state {w['state']!r} has no water matcher (ingest/{str(w['state']).lower()}_waters.py)")
    if w.get("county_field") and w["county_field"] not in safe:
        errs.append(f"waters.county_field {w['county_field']!r} is not a safe field")
    for p in w.get("no_water") or []:
        errs += _regex_errs("waters.no_water", p)
    for rule in block.get("filter") or []:
        if not isinstance(rule, dict) or not rule.get("field") or not rule.get("regex"):
            errs.append("each filter rule is {field, regex, exclude}")
        elif rule["field"] not in safe:
            errs.append(f"filter reads {rule['field']!r}, which is not a safe field")
        else:
            errs += _regex_errs("filter", rule["regex"])
    b = block.get("bounds")
    if b is not None and not (isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)
                              and b[0] < b[2] and b[1] < b[3]):
        errs.append("bounds is [lon_min, lat_min, lon_max, lat_max]")
    d = block.get("dedupe") or {}
    if not isinstance(d, dict) or set(d) - {"repeats", "order", "ignore"} or d.get("repeats", "suffix") not in ("suffix", "first"):
        errs.append("dedupe is {repeats: suffix | first, order, ignore}")
    h = block.get("history") or {}
    if not isinstance(h, dict):
        errs.append("history is a mapping")
        h = {}
    if set(h) - HISTORY_KEYS:
        errs.append(f"history: unknown keys {sorted(set(h) - HISTORY_KEYS)}")
    track = h.get("track") or []
    items = track.items() if isinstance(track, dict) else ((f, None) for f in track)
    for f, t in items:
        if t is not None and (not isinstance(t, dict) or set(t) - {"key", "label", "from", "skip_null"}):
            errs.append(f"history.track.{f} is {{key, label, from, skip_null}}")
            continue
        src = (t or {}).get("from") or f
        if not str(src).startswith("@") and src not in safe:
            errs.append(f"history.track reads {src!r}, which is not a safe field")
    for i, keys in enumerate(h.get("supersede") or []):
        if not isinstance(keys, list) or not keys:
            errs.append(f"history.supersede[{i}] is a list of templates")
            continue
        for t in keys:
            errs += spec_errors(f"history.supersede[{i}]", {"template": t}, safe)
    for k in ("max_error_share", "min_rows_ratio"):
        if k in block and not (isinstance(block[k], (int, float)) and 0 <= block[k] <= 1):
            errs.append(f"{k} is a share between 0 and 1")
    return errs


# ---------------------------------------------------------------- the record

def volume_fields(spec, row: dict, rec: dict, ctx: Ctx) -> dict:
    """volume_gal, volume_text, estimate_flag from a volume spec: {field, unit (gallons by default), estimate
    (estimated | measured | from_text), text (a template for volume_text), bare_number_text (appended to a bare
    number)}."""
    spec = norm_spec(spec)
    v, _ = lookup(spec, row)
    if v is None:
        return {"volume_gal": None, "volume_text": None, "estimate_flag": "unknown"}
    unit = VOLUME_UNITS[str(spec.get("unit", "gallons")).lower()]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = fnum(v)
        gal = int(round(f * unit)) if f is not None and f >= 0 else None
        est = "unknown"
        text = fmt_num(v)
    else:
        text = clean(v)
        f = fnum(text)
        if f is not None and unit != 1:
            gal, est = (int(round(f * unit)) if f >= 0 else None), "unknown"
        else:
            gal, est = parse_volume_gal(text)
    if spec.get("estimate") in ("estimated", "measured"):
        est = spec["estimate"] if gal is not None else "unknown"
    if spec.get("text"):
        vt = render(spec["text"], row, rec, ctx)
    elif spec.get("bare_number_text") and gal is not None and text.replace(".", "").isdigit():
        vt = f"{text} {spec['bare_number_text']}"
    else:
        vt = text or None
    return {"volume_gal": gal, "volume_text": vt, "estimate_flag": est}


def decoded_times(row: dict, ctx: Ctx) -> dict:
    """{field: ISO time} for the block's decoded_times fields, as read (no precision or sanity rule): the source's
    own values in readable form, cited beside the record's times."""
    dts = ctx.block["decoded_times"]
    kind = dts.get("parse", "datetime")
    out = {}
    for f in dts["fields"]:
        v = get(row, f)
        if v in (None, ""):
            continue
        n = fnum(v)
        if kind == "epoch_ms_wallclock" and n is not None:
            d = datetime.fromtimestamp(n / 1000, UTC).replace(tzinfo=None).replace(tzinfo=ctx.tz)
        elif kind in ("epoch_ms", "epoch_s") and n is not None:
            d = datetime.fromtimestamp(n / (1000 if kind == "epoch_ms" else 1), UTC).astimezone(ctx.tz)
        else:
            d = parse_datetime(v, ctx.tz)[0]
        out[f] = iso(d)
    return out


def _guarded(notes: dict, target: str, default, fn, *args):
    """fn(*args), or default when it fails on this row: the error is kept in raw._hook_errors (the runner counts it
    and fails the run when too many rows have one), so one field that cannot be read costs that field only, never
    the record or its key. A block that cannot run as written (SpecError) still stops the run."""
    try:
        return fn(*args)
    except SpecError:
        raise
    except Exception as e:  # noqa: BLE001 - never drop a record
        notes.setdefault("_hook_errors", []).append(f"record.{target}: {type(e).__name__}: {e}")
        return default


def build_fields(row: dict, ctx: Ctx) -> tuple[dict, dict]:
    """(event fields, raw notes) from one safe row by the block's record map. Times are read before the fields
    that may name them in a template; status is decided after the times (otherwise: from_end). A field whose spec
    fails on this row (its transform, a replace naming a missing group) is left empty with the error noted."""
    rmap = ctx.block.get("record") or {}
    notes: dict = {}
    rec: dict = {}
    # times first, start before end (an end may be start + duration)
    for t in TIME_FIELDS:
        if t not in rmap:
            continue
        dt, prec = _guarded(notes, t, (None, None), time_value, rmap[t], row, rec, ctx, notes, t)
        if t == "started_at":
            rec["_start_dt"] = dt
            rec["time_precision"] = prec
        if t == "ended_at" and dt is not None and prec in ("day", "month", "year") \
                and rec.get("time_precision") not in ("day", "month", "year", None) and "duration" not in norm_spec(rmap[t]):
            # an end known only to the day on a record timed to the minute: the latest it can be is that day's end
            notes.setdefault("_basis", {})[t] = ("the source gives the end's date only: ended_at is the end of that day "
                                                 "(the latest it can be)")
            nxt = (dt.astimezone(UTC) + timedelta(days=1, hours=1)).astimezone(dt.tzinfo)
            dt = datetime(nxt.year, nxt.month, nxt.day, tzinfo=dt.tzinfo)
        rec[t] = iso(dt)
        if t == "ended_at":
            rec["_end_dt"] = dt
    kinds = notes.pop("_time_kinds", set())
    if kinds:
        tzname = getattr(ctx.tz, "key", str(ctx.tz))
        notes["_time_basis"] = " ".join(TIME_BASIS[k].format(tz=tzname) for k in sorted(kinds))
    if "time_precision" in rmap:
        rec["time_precision"] = _guarded(notes, "time_precision", rec.get("time_precision"), value,
                                         rmap["time_precision"], row, rec, ctx, notes, "time_precision")
    for k, spec in rmap.items():
        if k in TIME_FIELDS or k in ("time_precision", "status", "event_type", "volume"):
            continue
        rec[k] = _guarded(notes, k, None, value, spec, row, rec, ctx, notes, k)
        if k in ("discharger_name", "authority") and "const" not in norm_spec(spec):
            rec[k] = scrub(rec[k])           # an owner's or filer's name field can hold a private person
    if "volume" in rmap:
        rec.update(_guarded(notes, "volume", {"volume_gal": None, "volume_text": None, "estimate_flag": "unknown"},
                            volume_fields, rmap["volume"], row, rec, ctx))
    # event type: the map's answer, else unknown with the source's label kept
    if "event_type" in rmap:
        s = norm_spec(rmap["event_type"])
        label, _ = lookup(s, row)
        et = _guarded(notes, "event_type", None, value, {**s, "unmapped": None} if "map" in s else s, row, rec, ctx,
                      None, "event_type")
        if et not in EVENT_TYPES:
            notes.setdefault("_problems", []).append(f"unknown event type {clean(label)!r}")
            et = "unknown"
        if label is not None:
            notes["_source_type"] = clean(label)
        rec["event_type"] = et
    # status: the map's answer; otherwise from_end (ended when an end is known, else unknown) or a literal
    sspec = norm_spec(rmap.get("status", {"otherwise": "from_end"}))
    st = None
    if "map" in sspec or "const" in sspec or "field" in sspec:
        st = _guarded(notes, "status", None, value, {**sspec, "unmapped": None}, row, rec, ctx, None, "status")
    if st not in STATUSES:
        other = sspec.get("otherwise", "from_end")
        st = ("ended" if rec.get("ended_at") else "unknown") if other == "from_end" else other
    start, end = rec.pop("_start_dt", None), rec.pop("_end_dt", None)
    if st in ("ongoing", "advisory_active") and rec.get("ended_at"):
        notes["_end_while_ongoing"] = rec["ended_at"]
        rec["ended_at"] = None
    if start is not None and end is not None and end < start:
        notes.setdefault("_problems", []).append("the end is before the start: ended_at left empty")
        rec["ended_at"] = None
        if st == "ended":
            st = "unknown"
    if st == "ended" and end is not None and rec.get("ended_at") \
            and end.astimezone(UTC) > ctx.fetched_dt + FUTURE_END_TOLERANCE:
        notes.setdefault("_problems", []).append(f"the end ({rec['ended_at']}) is after the fetch: not counted as ended")
        st = "unknown"
    rec["status"] = st
    # coordinates: numbers, inside the block's bounds
    for k in ("lat", "lon"):
        if k in rec:
            rec[k] = fnum(rec[k])
    b = ctx.block.get("bounds")
    if b and rec.get("lat") is not None and rec.get("lon") is not None:
        if not (b[0] <= rec["lon"] <= b[2] and b[1] <= rec["lat"] <= b[3]):
            notes["_coords_rejected"] = {"lat": rec["lat"], "lon": rec["lon"], "why": "outside the feed's bounds"}
            rec["lat"] = rec["lon"] = None
    if (rec.get("lat") is None) != (rec.get("lon") is None):
        rec["lat"] = rec["lon"] = None
    # raw notes the block names (decoded codes, each cited beside the record), and the source's times as read
    for key, spec in (ctx.block.get("raw_notes") or {}).items():
        notes[key] = _guarded(notes, f"raw_notes.{key}", None, value, spec, row, rec, ctx)
    if ctx.block.get("decoded_times"):
        notes["_decoded_times"] = decoded_times(row, ctx)
    return rec, notes
