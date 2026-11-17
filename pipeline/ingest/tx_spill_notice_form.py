"""Texas local spill notices: the shared reading of a utility's notice (not a feed).

Texas law makes a local government that spills 100,000 gallons or more of wastewater (50,000 near a drinking water
source or in a sensitive area) tell local officials and the local media within 24 hours, and fixes what the notice says
(30 TAC 319.302 and 319.303): the facility, the location, the estimated time and date and volume of the spill, the type,
the area potentially affected, the suspected cause, the actions taken and the personal precautions. TCEQ's form for it is
headed "NOTICE OF SPILL FROM A WASTEWATER FACILITY". Utilities post the notice with a news release (San Antonio Water
System attaches the form as a PDF; Austin Water and El Paso Water write the same facts into the release). The same spill
reaches TCEQ's open-data table (tx-tceq-sso-opendata) months later, with a date and no time of day.

This module holds what the Texas notice feeds share:
  - form_fields(text): the form's fields from the PDF's text. The contact line ("Contact for further information") is
    never returned: it names a staff member and a telephone number. A form whose fields were filled in as PDF form
    fields lists the labels empty and the values after the precautions, in the labels' order; both layouts are read.
  - spill_time(text, tz): the "estimated time and date of spill" as the notice writes it ("August 4, 2024 at
    approximately 8:30 pm", "Approximately 4:15 PM on 11/13/2024", "on Monday afternoon, Sept. 14"): minute precision
    with a clock time, day precision without one. Never an end: the form has no end field.
  - volume(text): the volume as written ("Spill estimated >100,000 gallons" stays text, a bound has no figure;
    "approximately 560,000 gallons" is 560,000, estimated). A volume is never computed.
  - water_of(area): the water the "area potentially affected" names, or None for an unnamed or intermittent creek,
    a storm drain, a pond, the ground or a plant's property: such a notice is listed with its city and county, unplaced.
  - street_place(text): a location with every house number dropped ("14819 Jones Maltsberger Rd near ..." becomes
    "Jones Maltsberger Rd near ...").
  - precautions(text): the precautions the form marks, only where the marks can be read (a form whose unmarked boxes
    print as a box glyph); "Don't swim in affected area streams, ponds or lakes." is then the advice, quoted. The form
    states no window: the site's caution applies by the existing rules.
  - link_tceq(records, rows): one spill, one record (module docstring of each feed): a notice whose operator, start day
    (within a day) and volume (consistent with the notice's figure or bound) meet a TCEQ row gets duplicate_of that row,
    so the structured state record is the one counted once TCEQ publishes it; until then the notice stands alone.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import common

CENTRAL = ZoneInfo("America/Chicago")
MOUNTAIN = ZoneInfo("America/Denver")
TCEQ_FILE = common.EVENTS_DIR / "tx-tceq-sso-opendata.json"

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTH_RE = (r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|"
            r"Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)")
DATE_WORDS = re.compile(MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:\s*,?\s*(\d{4}))?", re.I)
DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?|\b(noon|midnight)\b", re.I)

# the form's labels in its order; the contact label is read only to be skipped
LABELS = [("facility", r"Facility\s+Name\s*:"),
          ("contact", r"Contact\s+for\s+further\s+information\s*:"),
          ("location", r"Location\s+of\s+the\s+spill\s*:"),
          ("time", r"Estimated\s+time\s+and\s+date\s+of\s+spill\s*:"),
          ("volume", r"Estimated\s+volume\s+of\s+the\s+spill\s*\(number\s+of\s+gallons\)\s*:"),
          ("type", r"Type\s+of\s+spill\s*:\s*\(domestic\)\s*\(industrial\)\s*\(other\)\s*Explain\s+other\s*:"),
          ("area", r"Area\s+potentially\s+affected\s*:"),
          ("cause", r"Suspected\s+cause\s+of\s+spill\s*:")]
FORM_HEAD = re.compile(r"NOTICE\s+OF\s+SPILL\s+FROM\s+A\s+WASTEWATER\s+FACILITY", re.I)
ACTIONS_HEAD = re.compile(r"THE\s+FOLLOWING\s+ACTIONS\s+HAVE\s+BEEN\s+TAKEN", re.I)
PRECAUTION_LAST = re.compile(r"construction\s+and\s+maintenance\.?", re.I)
BOX = "☐"                       # an unmarked box as the PDF prints it ("☐")
SWIM = "Don't swim in affected area streams, ponds or lakes."


def _clean(s: str | None) -> str:
    s = re.sub(r"_{2,}", " ", s or "")
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip(" .;:-")


def form_fields(text: str) -> dict:
    """{facility, location, time, volume, type, area, cause} from a notice form's text (module docstring); {} when the
    text holds no form. The contact field is never returned."""
    m = FORM_HEAD.search(text or "")
    if not m:
        return {}
    body = text[m.end():]
    end = ACTIONS_HEAD.search(body)
    head = body[:end.start()] if end else body
    spans = []
    for key, pat in LABELS:
        lm = re.search(pat, head, re.I)
        if lm:
            spans.append((lm.start(), lm.end(), key))
    spans.sort()
    out = {}
    for i, (_, e, key) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else len(head)
        out[key] = _clean(head[e:nxt])
    if spans and not any(out.get(k) for k, _ in LABELS if k != "contact"):
        # filled as PDF form fields: the values follow the precautions, one line each, in the labels' order
        tail = body[end.end():] if end else ""
        last = list(PRECAUTION_LAST.finditer(tail))
        lines = [_clean(x) for x in (tail[last[-1].end():] if last else "").splitlines()]
        lines = [x for x in lines if x]
        order = [k for _, _, k in spans]
        if len(lines) >= len(order):
            out = dict(zip(order, lines))
    out.pop("contact", None)
    return {k: v for k, v in out.items() if v}


def facility_permit(facility: str | None) -> tuple[str | None, str | None]:
    """("Salado Creek Water Recycling Center", "WQ0010137008") from "Salado Creek Water Recycling Center – 10137-008"."""
    if not facility:
        return None, None
    m = re.search(r"[–-]\s*(\d{5})-(\d{3})\s*$", facility)
    if not m:
        return facility, None
    return _clean(facility[:m.start()]), f"WQ00{m.group(1)}{m.group(2)}"


def _month(s: str) -> int:
    k = s.lower().rstrip(".")
    return next(v for name, v in MONTHS.items() if name.startswith(k[:3]))


def _clock(m: re.Match) -> tuple[int, int]:
    if m.group(4):
        return (12, 0) if m.group(4).lower() == "noon" else (0, 0)
    h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
    return (h + 12 if m.group(3).lower() == "p" else h), mi


def spill_time(text: str | None, tz: ZoneInfo, published: date | None = None) -> tuple[str | None, str | None, str | None]:
    """(started_at, precision, the words read) for the spill's estimated time and date (module docstring). A date with
    no year takes the publication's year (the year before when that would fall after the publication)."""
    s = text or ""
    d = None
    m = DATE_WORDS.search(s)
    if m:
        y = int(m.group(3)) if m.group(3) else (published.year if published else None)
        if y is None:
            return None, None, None
        try:
            d = date(y, _month(m.group(1)), int(m.group(2)))
        except (ValueError, StopIteration):
            return None, None, None
        if not m.group(3) and published and d > published:
            d = date(y - 1, d.month, d.day)
    else:
        n = DATE_NUM.search(s)
        if n:
            y = int(n.group(3))
            y = y + 2000 if y < 100 else y
            try:
                d = date(y, int(n.group(1)), int(n.group(2)))
            except ValueError:
                return None, None, None
    if d is None:
        return None, None, None
    c = CLOCK.search(s)
    if c:
        h, mi = _clock(c)
        return datetime(d.year, d.month, d.day, h, mi, tzinfo=tz).isoformat(), "minute", _clean(s)
    return d.isoformat(), "day", _clean(s)


VOLUME = re.compile(r"((?:(?:approximately|about|an estimated|estimated|roughly|around|nearly|more than|over|greater than|"
                    r"in excess of|exceed(?:ed|s|ing)?|less than|under|up to|at least|[<>]=?)\s*)*)(\d[\d,]*(?:\.\d+)?)\s*(million\s+)?gallons(?!\s+(?:per|a|an)\s+"
                    r"(?:minute|hour|day))", re.I)


def volume(text: str | None) -> tuple[int | None, str, str | None]:
    """(gallons, estimate_flag, the words as written): a figure with no bound word is the figure ("approximately" makes it
    estimated); a bound ("more than 100,000 gallons", ">100,000") keeps only the words (common.parse_volume_gal)."""
    for m in VOLUME.finditer(text or ""):
        words = _clean(m.group(0))
        lead = (m.group(1) or "").lower()
        tail = (text or "")[m.start():m.end() + 30]
        bound = bool(re.search(r"more than|over|greater than|in excess|exceed|less than|under|up to|at least|[<>]", lead)) or \
            bool(re.search(r"\b(?:less than|up to|at least|under|between|from)\s+$", (text or "")[:m.start()][-14:], re.I)) or \
            bool(re.search(r"\d\s*(?:-|to|and)\s*\d", (text or "")[max(0, m.start() - 25):m.end()]))
        if bound:
            return None, "estimated", _clean(text) if len(_clean(text)) <= 80 else words
        gal, flag = common.parse_volume_gal(f"{m.group(2)} {'million ' if m.group(3) else ''}gallons")
        if gal is None:
            return None, flag, words
        est = bool(re.search(r"approx|about|estimat|roughly|around|nearly", lead + " " + (text or "")[:m.start()][-30:], re.I))
        return gal, "estimated" if est else flag, words
    return None, "unknown", None


NOT_A_WATER = re.compile(r"\b(?:unnamed|un-named|intermittent|unknown|storm\s*(?:drain|sewer|water)|ditch|pond|ground|soil|"
                         r"street|property|plant|facility|contained|none|n/a|wet\s+pond|drainage)\b", re.I)
NOT_AFTER_WATER = (r"(?!\s+(?:Road|Rd|Drive|Dr|Street|St|Avenue|Ave|Blvd|Boulevard|Lane|Ln|Parkway|Pkwy|Way|Court|Ct|Trail|"
                   r"Park|Water|Wastewater|Treatment|Recycling|Plant|Lift|Pump|Interceptor|Basin|Estates|Subdivision)\b)")
WATER_NAME = re.compile(r"\b((?:[A-Z][\w'’.-]*\s+){1,4}(?:Creek|River|Bayou|Lake|Reservoir|Branch|Bay|Arroyo|Draw|Canal))\b"
                        + NOT_AFTER_WATER + r"|\b(Rio\s+Grande)\b" + NOT_AFTER_WATER)


def water_of(area: str | None) -> str | None:
    """The named water of an "area potentially affected" (module docstring); None when it names none."""
    a = _clean(area)
    if not a:
        return None
    # a water the notice says the spill did not reach is not the affected area
    a = re.sub(r"\b(?:prior\s+to|before)\s+reaching\b.*$|\bdid\s+not\s+(?:reach|enter)\b.*$", "", a, flags=re.I)
    m = WATER_NAME.search(a)
    if not m:
        return None
    name = _clean(m.group(1) or m.group(2))
    name = re.sub(r"^(?:the|into|to|and|a|near)\s+", "", name, flags=re.I)
    if NOT_A_WATER.search(name) or len(name.split()) < 2:
        return None
    return name


def street_place(text: str | None) -> str | None:
    """A street location with each house number dropped (and the placeholder too: the street is what is kept)."""
    if not text:
        return None
    s = common.strip_house_numbers(_clean(text))
    s = s.replace(common.HOUSE_NUMBER_REMOVED + " ", "").replace(common.HOUSE_NUMBER_REMOVED, "")
    # a house number before a street name with no street word ("(6606 Swiss Oaks)"); a block ("500 Block of") and a
    # route number ("IH 10 E", "Hwy 90") stay
    s = re.sub(r"(?<![\w.,/:-])(?<!\bIH )(?<!\bUS )(?<!\bFM )(?<!\bSH )(?<!\bHwy )(?<!\bLoop )(?<!\bSpur )(?<!\bHighway )"
               r"(?<!\bInterstate )(?<!\bRoute )\d{2,6}[A-Za-z]?\s+(?=[A-Z][a-z]+)(?!Blocks?\b)", "", s)
    s = re.sub(r"\(\s*\)", "", s)
    return common.scrub_text(_clean(s)) or None


def safe_free_text(text: str | None) -> str | None:
    """Free text of a notice (area, cause) with house numbers dropped and contacts scrubbed."""
    return street_place(text) if text else None


def precautions(text: str) -> tuple[list[str] | None, str | None]:
    """(the precautions marked, the swimming advice when marked) where the marks can be read: the form prints an
    unmarked box as a glyph; with no glyph in the form at all, marked and unmarked look alike and nothing is read."""
    m = re.search(r"PERSONS\s+MAY\s+WISH\s+TO\s+TAKE\s+THE\s+FOLLOWING\s+PERSONAL\s+PRECAUTIONS", text or "", re.I)
    if not m or BOX not in text:
        return None, None
    tail = text[m.end():]
    last = list(PRECAUTION_LAST.finditer(tail))
    tail = tail[:last[-1].end()] if last else tail
    items = re.split(r"\n\s*(?=" + BOX + r"|[^\w\s]?\s*(?:Use only|Don.t swim|Always wash|Private well))", tail)
    marked, swim = [], None
    for it in items:
        it2 = it.strip()
        if not it2 or it2.startswith(BOX):
            continue
        line = _clean(re.sub(r"^[^\w]+", "", it2))
        if line:
            marked.append(line)
            if re.match(r"Don.t\s+swim", line, re.I):
                swim = SWIM
    return marked or None, swim


# ---------------------------------------------------------------- one spill, one record

MATCH_PAD_DAYS = 1


def tceq_rows(path=TCEQ_FILE) -> list[dict]:
    d = common.read_json(path, {}) or {}
    return [r for r in d.get("records", []) if r.get("started_at")]


def _day(ts) -> date | None:
    try:
        return date.fromisoformat(str(ts or "")[:10])
    except ValueError:
        return None


def _water_key(t) -> str:
    """A water's name for comparison: lower case, letters only, without a TCEQ prefix ("SPILLED INTO")."""
    t = re.sub(r"(?i)\bspilled\s+(?:in)?to\b|\briver/creek\b", " ", str(t or ""))
    return re.sub(r"[^a-z]", "", t.lower())


def _bound(rec: dict) -> int | None:
    m = re.search(r"(\d[\d,]*)", rec.get("volume_text") or "")
    return int(m.group(1).replace(",", "")) if m and rec.get("volume_gal") is None else None


def volume_consistent(rec: dict, row: dict) -> bool:
    theirs = row.get("volume_gal")
    if theirs is None:
        return True
    if rec.get("volume_gal"):
        return rec["volume_gal"] / 2 <= theirs <= rec["volume_gal"] * 2
    b = _bound(rec)
    return b is None or theirs >= b * 0.9


def same_operator(rec: dict, row: dict) -> bool:
    if rec.get("discharger_id") and rec["discharger_id"] == row.get("discharger_id"):
        return True
    if row.get("discharger_id") and row["discharger_id"] in ((rec.get("raw") or {}).get("operator_ids") or []):
        return True
    mine = (rec.get("raw") or {}).get("state_permit_prefix")
    theirs = (row.get("raw") or {}).get("state_permits") or []
    return bool(mine) and any(str(p).startswith(mine) for p in theirs)


def link_tceq(records: list[dict], rows: list[dict]) -> int:
    """Set duplicate_of on each notice that meets a TCEQ row (module docstring); returns the count."""
    n = 0
    used: set[str] = set()
    # notices that name a water first, then the earliest, so a row goes to the notice it fits best
    for rec in sorted(records, key=lambda r: (not r.get("waterbody_text"), r.get("started_at") or "")):
        rec["duplicate_of"] = None
        (rec.get("raw") or {}).pop("tceq_match", None)
        d = _day(rec.get("started_at"))
        if d is None:
            continue
        cands = []
        mine = _water_key(rec.get("waterbody_text"))
        permit = (rec.get("raw") or {}).get("state_permit")
        for row in rows:
            s = _day(row.get("started_at"))
            if s is None or row["event_id"] in used or abs((s - d).days) > MATCH_PAD_DAYS or \
                    not same_operator(rec, row) or not volume_consistent(rec, row):
                continue
            theirs = _water_key(row.get("waterbody_text"))
            if mine and theirs and mine not in theirs and theirs not in mine:
                continue            # each names a different water: two spills
            same_water = bool(mine and theirs)
            same_permit = bool(permit) and permit in ((row.get("raw") or {}).get("state_permits") or [])
            cands.append((0 if same_water else 1, 0 if same_permit else 1, abs((s - d).days),
                          str(row.get("source_record_id") or ""), row))
        if not cands:
            continue
        cands.sort(key=lambda c: c[:4])
        row = cands[0][4]
        used.add(row["event_id"])
        rec["duplicate_of"] = row["event_id"]
        rec["raw"]["tceq_match"] = {"event_id": row["event_id"], "days_apart": cands[0][2],
                                    "tceq_volume_gal": row.get("volume_gal"), "candidates": len(cands),
                                    "same_water": cands[0][0] == 0,
                                    "basis": "same operator, start within a day, volume consistent with the notice's"}
        n += 1
    return n
