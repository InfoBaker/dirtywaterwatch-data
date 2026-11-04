"""The declarative field map of a generic ingester (docs/generic-ingesters.md): from one source row to the
event record of docs/plan.md §3. Not a feed; the runner is `python -m ingest.generic <source-id>`.

A `fetch` block in data/sources/<id>.yaml names the platform and endpoint, the safe fields (everything else is
dropped before anything is read or stored), the free-text fields the scrubbers run on, and `record:`, one entry
per event field. Each entry is a value spec:

  "FIELD"                                   the field's text (shorthand for {field: FIELD})
  {field: F}  or {field: [F1, F2]}          the first non-empty field; a fallback used is noted in raw._basis
  {const: X}                                a constant
  {template: "{F|filter|filter:arg}-..."}   a string built from row fields ({@started_at} reads a record field);
                                            empty when a field it names is empty, unless |default:x is given
  upper / lower / regex + replace / map + unmapped / parse / transform   applied in that order

Times (started_at, ended_at, reported_at, published_at, source_updated_at) take a time spec: {field, parse:
datetime | epoch_ms | epoch_s | epoch_ms_wallclock, formats, time (a separate time-of-day field), precision};
ended_at may instead be {duration: {days, hours, minutes}} (start plus duration). Naive times are read in the
block's time_zone. A time is never invented: what the source does not give stays null.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from common import (DATA_DIR, EVENT_TYPES, KEEP_KEYS, NAME_KEYS, PERSONAL_KEYS, STATUSES, parse_volume_gal, read_json,
                    scrub_text)

TIME_FIELDS = ("started_at", "ended_at", "reported_at", "published_at", "source_updated_at")
PRECISIONS = {"minute", "hour", "day", "month", "year", "poll"}
# record fields a value spec may fill (the runner owns event_id, source_id, fetched_at, raw and the water match)
VALUE_FIELDS = {"source_record_id", "parent_event_id", "discharger_id", "discharger_name", "npdes_permit", "outfall_id",
                "outfall_name", "waterbody_text", "coord_precision_m", "material", "authority", "advice_text",
                "advice_window_hours", "advice_window_basis", "source_url", "volume_text", "estimate_flag",
                "time_precision", "event_type", "status", "lat", "lon", "coord_source"}
SPECIAL_FIELDS = set(TIME_FIELDS) | {"volume"}
SPEC_KEYS = {"field", "const", "template", "upper", "lower", "regex", "replace", "map", "unmapped", "match", "parse",
             "transform", "formats", "time", "time_formats", "precision", "duration", "otherwise", "unit",
             "estimate", "text", "bare_number_text", "round"}
DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y")
DATETIME_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%y %H:%M", "%m/%d/%y %I:%M %p")
TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p", "%H%M")
VOLUME_UNITS = {"gallons": 1, "gal": 1, "mg": 1_000_000, "million_gallons": 1_000_000, "liters": 0.264172,
                "m3": 264.172}
# the receiving-water text that names no surface water (kept as text, placed on no water)
NO_WATER = re.compile(r"^\s*(n\s*/?\s*a|none|no|unknown|unk|null|nil|tbd|-+|0|ground|groundwater|ground water|"
                      r"the ground|on the ground|ground surface|grass|soil|land|storm ?drains?|storm ?sewer|"
                      r"storm ?drain system|side ditch|ditch)\s*[.!]*\s*$", re.I)
NOT_REACHED = re.compile(r"\b(did not|didn'?t|does not|doesn'?t|never|no discharge)\s+(enter|reach|go)", re.I)
# a person named after an honorific in free text; "Dr" is left out (in addresses it is Drive)
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Mx|Miss)\.?\s+[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)?")
REDACTED = "[name removed]"
ADDR_WORDS = {"street": "st", "str": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr", "lane": "ln",
              "court": "ct", "place": "pl", "boulevard": "blvd", "parkway": "pkwy", "highway": "hwy", "terrace": "ter",
              "circle": "cir", "square": "sq", "turnpike": "tpke", "east": "e", "west": "w", "north": "n",
              "south": "s", "mount": "mt", "saint": "st", "route": "rt", "rte": "rt", "pike": "pk", "trail": "trl"}
TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


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


# ---------------------------------------------------------------- small helpers

def clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).replace("\xa0", " ").split())


def slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(s).lower()).strip("-")


def norm_addr(s) -> str:
    """A street address as a key: lower case, punctuation dropped, street words abbreviated."""
    t = clean(s).lower().replace("&", " and ")
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


def resolve(dotted: str):
    """A Python function named by its dotted path ("ingest.generic.transforms.md_mde_coords")."""
    mod, _, name = str(dotted).rpartition(".")
    if not mod:
        raise SpecError(f"transform {dotted!r} is not a dotted module.function path")
    fn = getattr(importlib.import_module(mod), name, None)
    if not callable(fn):
        raise SpecError(f"transform {dotted!r} is not a function")
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


# ---------------------------------------------------------------- templates

def _filter(v, name: str, arg: str | None, ctx: Ctx):
    if name == "default":
        return v if clean(v) else arg
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
    if name == "num":
        return fmt_num(v)
    if name == "int":
        f = fnum(v)
        return str(int(f)) if f is not None else clean(v)
    if name == "compact":           # a time as a key: 20260523T0205 at minute precision, 20260523 at day
        dt, prec = v if isinstance(v, tuple) else (v, None)
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                return clean(dt)
        if isinstance(dt, datetime):
            return dt.strftime("%Y%m%d") + (dt.strftime("T%H%M") if prec not in ("day", "month", "year") else "")
        return clean(dt)
    if name == "strftime":
        dt = v[0] if isinstance(v, tuple) else v
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        return dt.strftime(arg or "%Y-%m-%d")
    raise SpecError(f"unknown template filter {name!r}")


def render(template: str, row: dict, rec: dict | None, ctx: Ctx) -> str | None:
    """'{npdes_no|upper|slug|default:none}-{@started_at|compact}' -> text, or None when a field it names is empty
    and has no default. {@x} reads the record field x being built (a time with its precision for |compact)."""
    empty = False

    def sub(m):
        nonlocal empty
        name, *filters = [p.strip() for p in m.group(1).split("|")]
        if name.startswith("@"):
            f = name[1:]
            v = (rec or {}).get(f)
            if f == "started_at" and v is not None:
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


def template_fields(template: str) -> list[str]:
    return [m.group(1).split("|")[0].strip() for m in TEMPLATE_RE.finditer(template)
            if not m.group(1).split("|")[0].strip().startswith("@")]


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


def value(spec, row: dict, rec: dict | None, ctx: Ctx, notes: dict | None = None, target: str = ""):
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


def parse_datetime(v, tz: ZoneInfo, formats=None) -> tuple[datetime | None, str | None]:
    """(aware datetime, precision) from a source's text: the block's formats, else ISO 8601, RFC 2822 (RSS) and the
    common US forms. A date with no time of day is precision day."""
    s = clean(v)
    if not s:
        return None, None
    for fmt in formats or ():
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        timed = any(c in fmt for c in ("%H", "%I", "%M"))
        return _localize(dt, tz), ("minute" if timed else "day")
    if formats:
        return None, None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=tz), "day"
    try:
        return _localize(datetime.fromisoformat(s.replace("Z", "+00:00")), tz), "minute"
    except ValueError:
        pass
    if re.search(r"[A-Za-z]{3},?\s+\d|\d{1,2}\s+[A-Za-z]{3}\s+\d{4}", s):
        try:
            dt = parsedate_to_datetime(s)
            if dt is not None:
                return _localize(dt, tz), "minute"
        except (TypeError, ValueError):
            pass
    for fmt in DATETIME_FORMATS:
        try:
            return _localize(datetime.strptime(s, fmt), tz), "minute"
        except ValueError:
            pass
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


def parse_epoch(v, kind: str, tz: ZoneInfo) -> datetime | None:
    f = fnum(v)
    if f is None:
        return None
    try:
        t = datetime.fromtimestamp(f / (1000 if kind != "epoch_s" else 1), UTC)
    except (OverflowError, OSError, ValueError):
        return None
    if kind == "epoch_ms_wallclock":     # local wall-clock time stored as if it were UTC (common on ArcGIS layers)
        return t.replace(tzinfo=None).replace(tzinfo=tz)
    return t.astimezone(tz)


def time_value(spec, row: dict, rec: dict, ctx: Ctx, notes: dict, target: str) -> tuple[datetime | None, str | None]:
    """(aware datetime, precision) for one time field of the record."""
    spec = norm_spec(spec)
    if "duration" in spec:
        start = rec.get("_start_dt")
        dur = duration(spec["duration"], row)
        if start is None or dur is None:
            return None, None
        notes.setdefault("_basis", {})[target] = "start plus the source's duration (" + ", ".join(
            f"{k} {v}" for k, v in spec["duration"].items()) + ")"
        return start + dur, rec.get("time_precision")
    if "const" in spec:
        return parse_datetime(spec["const"], ctx.tz)
    v, used = lookup(spec, row)
    fields = spec.get("field")
    if used and isinstance(fields, list) and used != fields[0]:
        notes.setdefault("_basis", {})[target] = f"{used} (the first of {', '.join(fields)} with a value)"
    kind = spec.get("parse", "datetime")
    if v is None:
        return None, None
    if kind in ("epoch_ms", "epoch_s", "epoch_ms_wallclock"):
        dt, prec = parse_epoch(v, kind, ctx.tz), "minute"
    elif kind == "date":
        dt, prec = parse_datetime(v, ctx.tz, spec.get("formats"))
        if dt is not None:
            dt, prec = datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo), "day"
    else:
        dt, prec = parse_datetime(v, ctx.tz, spec.get("formats"))
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
    return dt, prec


def duration(spec: dict, row: dict) -> timedelta | None:
    """start + duration: {days: F, hours: F, minutes: F} (any of them); None when none is given, one is not a
    number or one is negative."""
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
    """A field name that looks like it holds a person's name, email or phone (common.strip_personal's rule)."""
    leaf = str(name).split(".")[-1]
    return bool(NAME_KEYS.search(leaf) or (PERSONAL_KEYS.search(leaf) and not KEEP_KEYS.search(leaf)))


def safe_row(row: dict, block: dict) -> dict:
    """Only the safe fields (a dotted safe field keeps that nested value under its dotted name); free-text fields
    scrubbed (emails, phones, staff titles, names after an honorific)."""
    out = {}
    for f in block["safe_fields"]:
        v = row[f] if f in row else get(row, f)
        if f in row or v is not None:
            out[f] = v
    for f in block.get("free_text") or ():
        if isinstance(out.get(f), str):
            out[f] = scrub_people(scrub_text(out[f]))
    return out


# ---------------------------------------------------------------- the record

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


def validate(block: dict, source_id: str = "") -> list[str]:
    """Problems that stop a fetch block from running (an empty list when it can run)."""
    errs = []
    if not isinstance(block, dict):
        return ["fetch is not a mapping"]
    if not block.get("platform"):
        errs.append("fetch.platform is missing")
    safe = block.get("safe_fields")
    if not isinstance(safe, list) or not safe:
        errs.append("fetch.safe_fields is missing: every block lists the fields it may keep")
        safe = []
    reviewed = block.get("reviewed_fields") or {}
    for f in safe:
        if personal_field(f) and f not in reviewed:
            errs.append(f"safe field {f!r} looks personal (a name, email or phone); list it under reviewed_fields "
                        f"with the reason it is not, or leave it out")
    rec = block.get("record") or {}
    if not isinstance(rec, dict) or "source_record_id" not in rec:
        errs.append("fetch.record.source_record_id is missing")
        rec = rec if isinstance(rec, dict) else {}
    for k, spec in rec.items():
        if k not in VALUE_FIELDS and k not in SPECIAL_FIELDS:
            errs.append(f"record.{k} is not an event field a block may fill")
            continue
        s = norm_spec(spec)
        bad = set(s) - SPEC_KEYS
        if bad:
            errs.append(f"record.{k}: unknown keys {sorted(bad)}")
        for f in spec_fields(spec):
            if f not in safe and f.split(".")[0] not in safe:
                errs.append(f"record.{k} reads {f!r}, which is not a safe field")
        if k == "event_type" and "const" in s and s["const"] not in EVENT_TYPES:
            errs.append(f"record.event_type {s['const']!r} is not an event type")
        if k == "event_type" and isinstance(s.get("map"), dict):
            for out in s["map"].values():
                if out not in EVENT_TYPES:
                    errs.append(f"record.event_type maps to {out!r}, not an event type")
        if k == "status" and isinstance(s.get("map"), dict):
            for out in s["map"].values():
                if out not in STATUSES:
                    errs.append(f"record.status maps to {out!r}, not a status")
        if k == "time_precision" and "const" in s and s["const"] not in PRECISIONS:
            errs.append(f"record.time_precision {s['const']!r} is not a precision")
    for f in block.get("free_text") or ():
        if f not in safe:
            errs.append(f"free_text field {f!r} is not a safe field")
    if block.get("time_zone"):
        try:
            ZoneInfo(block["time_zone"])
        except Exception:  # noqa: BLE001
            errs.append(f"unknown time_zone {block['time_zone']!r}")
    w = block.get("waters") or {}
    for k, fn in [("transform", f) for f in listify(block.get("transform"))] + \
                 [("post", f) for f in listify(block.get("post"))] + [("waters.matcher", f) for f in listify(w.get("matcher"))]:
        try:
            resolve(fn)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{k}: {e}")
    if w.get("county_field") and w["county_field"] not in safe:
        errs.append(f"waters.county_field {w['county_field']!r} is not a safe field")
    for rule in block.get("filter") or []:
        if not isinstance(rule, dict) or not rule.get("field") or not rule.get("regex"):
            errs.append("each filter rule is {field, regex, exclude}")
        elif rule["field"] not in safe:
            errs.append(f"filter reads {rule['field']!r}, which is not a safe field")
    return errs


def volume_fields(spec, row: dict, rec: dict, ctx: Ctx) -> dict:
    """volume_gal, volume_text, estimate_flag from a volume spec: {field, unit (gallons by default), estimate
    (estimated | measured | from_text), text (a template for volume_text), bare_number_text (appended to a bare
    number), round}."""
    spec = norm_spec(spec)
    v, _ = lookup(spec, row)
    if v is None:
        return {"volume_gal": None, "volume_text": None, "estimate_flag": "unknown"}
    unit = VOLUME_UNITS.get(str(spec.get("unit", "gallons")).lower())
    if unit is None:
        raise SpecError(f"unknown volume unit {spec.get('unit')!r}")
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


def build_fields(row: dict, ctx: Ctx) -> tuple[dict, dict]:
    """(event fields, raw notes) from one safe row by the block's record map. Times are read before the fields
    that may name them in a template; status is decided after the times (otherwise: from_end)."""
    rmap = ctx.block.get("record") or {}
    notes: dict = {}
    rec: dict = {}
    # times first, start before end (an end may be start + duration)
    for t in TIME_FIELDS:
        if t not in rmap:
            continue
        dt, prec = time_value(rmap[t], row, rec, ctx, notes, t)
        if t == "started_at":
            rec["_start_dt"] = dt
            rec["time_precision"] = prec
        rec[t] = iso(dt)
        if t == "ended_at":
            rec["_end_dt"] = dt
    if "time_precision" in rmap:
        rec["time_precision"] = value(rmap["time_precision"], row, rec, ctx, notes, "time_precision")
    for k, spec in rmap.items():
        if k in TIME_FIELDS or k in ("time_precision", "status", "event_type", "volume"):
            continue
        rec[k] = value(spec, row, rec, ctx, notes, k)
    if "volume" in rmap:
        rec.update(volume_fields(rmap["volume"], row, rec, ctx))
    # event type: the map's answer, else unknown with the source's label kept
    if "event_type" in rmap:
        s = norm_spec(rmap["event_type"])
        label, _ = lookup(s, row)
        et = value({**s, "unmapped": None} if "map" in s else s, row, rec, ctx, None, "event_type")
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
        st = value({**sspec, "unmapped": None}, row, rec, ctx, None, "status")
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
    return rec, notes
