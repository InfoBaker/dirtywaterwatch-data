"""Portland Environmental Services news RSS (Oregon): the City of Portland's CSO Advisories and Sewage Advisories as
dated sewage reports in the City's own window -> data/build/events/or-bes-news-rss.json

Source
  https://www.portland.gov/bes/news/rss (registry: or-bes-news-rss), the Bureau of Environmental Services' news as RSS
  2.0 (the 25 latest items: title, link, description, guid, pubDate), no key; each advisory's own page for its text.
  BES publishes a "CSO Advisory" for each combined sewer overflow to the Willamette River or the Columbia Slough and a
  "Sewage Advisory" (or "Advisory: Sewage Release to ...") for a sewage release elsewhere, among other news. The duty
  behind them is a permit condition, not a statute: DEQ's NPDES general conditions (Schedule F) require the permittee
  to "alert the public, health agencies and other affected entities" of an overflow that threatens public health, by
  its own Emergency Response and Public Notification Plan, with no deadline and no channel set.
  25 items on 2026-11-07: 13 sewage advisories (4 CSO, 9 sewage releases) from 2025-11-21 to 2026-10-22.

Which items are read
  An item is a sewage advisory when its title names "CSO", "combined sewer overflow", "sewer overflow" or "sewage"
  (TITLE_RE) and not treated wastewater or effluent (NOT_SEWAGE_TITLE). Every
  other item is not read (rates, traffic advisories, projects; "Treated wastewater that was not dechlorinated enters
  the Columbia Slough" of 2025-12-19 is treated effluent for which BES advised no precautions: not a sewage report).
  meta.not_read counts them.

Record rules (rules only: no model, no geocoding)
  - Key: the item's node (the guid "https://www.portland.gov/node/57178#2025-12-21T02:00:00" -> "57178"); the guid's
    time changes when BES updates the page, and the page is then read again. A second release the same advisory
    reports ("Around noon on December 9, and again around 8 p.m. on December 18") is its own record "<node>-2", its
    published_at the page's update (the second release was announced there).
  - Type: cso when the title or text says "CSO" or "combined sewer overflow" (BES's word), else sso ("sewage
    release"); raw._type_basis says which.
  - Times, all America/Los_Angeles (Portland; raw.time_zone): BES's page gives "Published" and, when edited,
    "Updated": published_at and source_updated_at. The RSS pubDate follows the page's last update (the 2025-12-18 CSO
    advisory's pubDate is its expiry, 2025-12-21 02:00), so it is kept as raw.rss_pub_date and is never the start.
    reported_at stays null (BES gives no time it received a report). started_at is the text's own start, in this
    order (START_RULES): "the overflow began/started around <time> on <date>", "Start Time: <time> <date>", "occurred at
    approximately <time> on <date>", "Around/At approximately <time> on <date>, crews responded/reported" (a crew's
    response: raw.start_basis says the release began at or before it), "Around <time>, crews responded" or "Crews
    responded at approximately <time>" with the day from the text ("On Friday, December 5", "Wednesday morning" read
    as the latest such day on or before publication); else the day alone ("On Wednesday, October 21, City crews
    responded"; "first reported on October 18"), precision day; else the publication time, the latest the release can
    have begun (raw.start_basis says so). A date with no year takes the publication's year, or the year before when
    that would put it after the publication.
  - End, never invented: "ended around <time> on <date>", "stopped (the overflow) by/at <time> [<date>]", "lasted
    about <n> minutes/hours" (start plus the duration). "The release has stopped" with no time: the publication time
    as an upper bound (raw.ended_at_precision "bound"). A CSO advisory that gives only its expiry ("This advisory
    expired at 3:34am on March 16, 2026") and the advice "for 48 hours after it stops": the overflow's end is the
    expiry less those 48 hours, so the window drawn ends exactly at BES's expiry (raw.end_basis says so; the expiry is
    raw.advisory_expires_at): that end is the latest the overflow can have stopped, so it is a bound (raw.ended_at_precision
    "bound", "ended by"). Otherwise no end: status ongoing when the text says the release is ongoing, or when the City
    advises avoiding a named water and states no end or stop (raw.status_basis: red while it stands, then "end not
    confirmed"); else unknown. raw.ended_at_precision is minute (a stated time), bound, or day.
  - The City's window: an advisory that says "Avoid contact ... during the overflow and for 48 hours after it stops"
    carries advice_window_hours 48 with BES's sentence as advice_window_basis: the status build draws it as the
    authority's own red (rule red.event) from the start to 48 hours after the end, then the site's caution to 72 hours
    (data/rules.json). An advisory with no such sentence (most sewage releases: "follow any posted signage") has no
    window of its own: red while the release runs, the site's 72-hour caution after it ends.
  - Water: the waters the text names (WATER_RULES: "affects the stretch of the <W>", "released/overflow/discharges to
    the <W>", "impacting/affecting <W>", "advisory has been issued for the <W> and/or <W>", "avoid (contact with) <W>
    and <W>"), a named water being up to three capitalised words before River, Creek, Slough, Lake, Bay or Channel.
    waterbody_text joins them with "; "; the status build places the report by those names (a CSO report on the
    permit's outfalls of the water it names). The stretch BES names ("downstream of the Ross Island Bridge") is kept
    as raw.stretch_text. A text that says the sewage reached no water ("all sewage currently remains in the excavation
    hole", "a nearby catch basin that reconnects to the city sewer") sets raw.reached_water false with the sentence as
    raw._no_water_reason: kept, listed, placed on no water. A text that names no water is kept and placed nowhere.
    No point: BES gives none, and a street named in the text is never geocoded.
  - Operator: a CSO advisory is Portland's (discharger or-portland-bes, permit OR0026905, the Columbia Boulevard plant's
    permit that covers the combined sewer outfalls). A sewage release BES says comes from private property or a
    private outfall names no operator (raw.private_source); any other is BES's collection system (discharger
    or-portland-bes, no permit: the separate system's releases are not tied to one permit in the text).
  - Volume: one gallon figure in the text is volume_gal (estimate_flag estimated when the text says estimated or
    approximately); several are kept as volume_text.
  - advice_text: BES's own sentences of advice ("Avoid contact ...", "the public is advised to ...").
  - History: the feed holds 25 items, so the previous run's records are carried and a record is never dropped
    because its item left the feed. A page that could not be read leaves a record from the RSS text with
    raw.page_read false, read again next run.

Privacy: each page's "Contact" block (the public information officer's address and telephone) and everything after
the article (prevention tips, the hotline, related links) are cut before anything is kept; data/raw keeps only the
items' title, link, guid, pubDate and description and each page's dates, label and article lines, with house numbers
removed (common.strip_house_numbers) and emails and telephone numbers scrubbed (common.scrub_text). common.event runs
common.strip_personal on raw. tests/test_ingest_or.py proves a contact name, an e-mail and a house number never reach
a record.

Cadence: hourly. Run from pipeline/:  python -m ingest.or_bes_news [--file saved.json]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, strip_house_numbers,
                    write_events)

SOURCE_ID = "or-bes-news-rss"
FEED = "https://www.portland.gov/bes/news/rss"
TZ = ZoneInfo("America/Los_Angeles")
AUTHORITY = "City of Portland Environmental Services (advisory)"
DISCHARGER_ID = "or-portland-bes"
CSO_PERMIT = "OR0026905"
TIMEOUT = (60, 600)
SAFE_FORMAT = "dww-or-bes-safe/1"
TITLE_RE = re.compile(r"\b(?:CSO|combined\s+sewer\s+overflow|sewer\s+overflow|sewage)\b", re.I)
# treated effluent (the plant's own discharge before a final step) is not a sewage report, whatever the title says
NOT_SEWAGE_TITLE = re.compile(r"\btreated\s+(?:wastewater|effluent)\b", re.I)
CSO_RE = re.compile(r"\bCSOs?\b|combined\s+sewer\s+overflow", re.I)
# the page's article ends at the first of these lines; nothing after it is kept (the contact block is among them)
CUT_RE = re.compile(r"^(?:Help prevent\b|(?:(?:Media|Press|News|Public)\s+)?Contacts?|About Environmental Services|About CSOs|"
                    r"Stay updated and learn more|See something we could improve|Related|Topics)\b", re.I)
SKIP_LINES = {"label:", "in this article", "translate this page", "key details"}
MONTHS = ("january february march april may june july august september october november december").split()
_MON = r"(?P<{n}mon>January|February|March|April|May|June|July|August|September|October|November|December)"
_DATE = (_MON + r"\.?\s+(?P<{n}day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<{n}year>\d{{4}}))?"
         r"|(?P<{n}m>\d{{1,2}})/(?P<{n}d>\d{{1,2}})/(?P<{n}y>\d{{2,4}})")
_TIME = r"(?P<{n}t>midnight|noon|\d{{1,2}}(?::\d{{2}})?\s*[ap]\.?\s*m\b\.?)"
WEEKDAYS = ("monday tuesday wednesday thursday friday saturday sunday").split()
_WEEKDAY = r"(?P<wd>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"


def D(n: str = "") -> str:
    return "(?:" + _DATE.format(n=n) + ")"


def T(n: str = "") -> str:
    return _TIME.format(n=n)


_ABOUT = r"(?:around|at|approximately|about|\s)*"
# (pattern, basis): the start, in order; groups t (time) and an optional date
START_RULES = [
    (re.compile(rf"overflow (?:began|started)\s{_ABOUT}{T()} on (?:\w+day,\s*)?{D()}", re.I),
     "the overflow's start as the advisory gives it"),
    (re.compile(rf"Start Time:\s*{T()}\s+{D()}", re.I), "the advisory's start time"),
    (re.compile(rf"occurred at approximately {T()} on {D()}", re.I), "the release's time as the advisory gives it"),
    (re.compile(rf"(?:At approximately|Around|At about|At) {T()} on {D()},? (?:City )?crews (?:responded|reported)",
                re.I),
     "the time City crews responded to or reported the release: it began at or before this time"),
    (re.compile(rf"\bAround {T()} on {D()}", re.I),
     "the time the advisory gives for the release: it began at or before this time"),
]
# a time with the day elsewhere in the text
TIME_ONLY_RULES = [
    (re.compile(rf"(?:At approximately|Around) {T()},? crews responded", re.I),
     "the time City crews responded to the release: it began at or before this time"),
    (re.compile(rf"crews responded (?:at approximately|around|at) {T()}", re.I),
     "the time City crews responded to the release: it began at or before this time"),
]
DAY_RULES = [
    (re.compile(rf"\bOn {_WEEKDAY},? {D()},? (?:City )?crews", re.I),
     "the day City crews responded, as the advisory gives it (no time of day)"),
    (re.compile(rf"first reported on {D()}", re.I), "the day the release was first reported (no time of day)"),
]
WEEKDAY_PART = re.compile(rf"\b(?:responded|reported)\s+{_WEEKDAY}\s+(?:morning|afternoon|evening|night)|"
                          rf"\bOn {_WEEKDAY.replace('wd', 'wd2')}\s+(?:morning|afternoon|evening|night)", re.I)
AGAIN = re.compile(rf"and again\s{_ABOUT}{T()} on {D()}", re.I)
END_RULES = [
    (re.compile(rf"ended\s{_ABOUT}{T()} on {D()}", re.I), "the overflow's end as the advisory gives it"),
    (re.compile(rf"stopped (?:the overflow |the release )?(?:by|at|around) {T()}(?:\s+(?:on\s+)?{D()})?", re.I),
     "the time the advisory says the overflow was stopped"),
]
DURATION = re.compile(r"lasted (?:about|approximately|around)?\s*(?P<n>\d+|one|two|three|four|five|six|seven|eight|nine|"
                      r"ten|eleven|twelve)\s+(?P<u>minutes?|hours?)", re.I)
NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
STOPPED = re.compile(r"\b(?:release|overflow)s?\s+(?:has|have)\s+stopped\b", re.I)
EXPIRY_RULES = [
    re.compile(rf"advisory expired at {T()} on (?:\w+day,\s*)?{D()}", re.I),
    re.compile(rf"advisory has been issued for .{{0,80}}? through {T()},? {D()}", re.I),
]
ONGOING = re.compile(r"\b(?:is|remains)\s+(?:currently\s+)?ongoing\b", re.I)
AVOID_WATER = re.compile(r"\b(?:avoid|Avoid)\s+(?:contact with\s+)?(?:the\s+)?(?:[A-Z][a-z]+\s){1,3}"
                         r"(?:River|Creek|Slough|Lake|Bay|Channel)\b")
ADVICE48 = re.compile(r"for 48 hours after (?:it|the overflow|the release) (?:stops|stopped)", re.I)
PRIVATE = re.compile(r"\bprivate (?:property|outfall)\b", re.I)
NO_WATER = [re.compile(r"[^.]*\b(?:all )?(?:the )?sewage (?:currently )?remains in the [^.]*\.", re.I),
            re.compile(r"[^.]*\b(?:catch basin|inlet) that reconnects to the (?:city )?sewer[^.]*\.", re.I)]
_W = r"(?P<w{i}>(?:[A-Z][a-z]+\s){{1,3}}(?:River|Creek|Slough|Lake|Bay|Channel))"
WATER_RULES = [
    re.compile(r"affects the stretch of the " + _W.format(i=1)),
    re.compile(r"(?:released|releases?|overflow|discharges?|flowing)\s+(?:in)?to\s+(?:the\s+)?" + _W.format(i=1)),
    re.compile(r"(?:impacting|affecting|Impacting|Affecting)\s+(?:the\s+)?" + _W.format(i=1)),
    re.compile(r"issued for the " + _W.format(i=1) + r"(?:\s+and/or\s+(?:the\s+)?" + _W.format(i=2) + ")?"),
    re.compile(r"(?:avoid|Avoid)\s+(?:contact with\s+)?(?:the\s+)?" + _W.format(i=1) + r"(?:\s+and\s+(?:the\s+)?"
               + _W.format(i=2) + ")?"),
]
STRETCH = re.compile(r"(?:affects the stretch of|avoid(?: contact with)?) the [A-Z][\w ]*?(?:River|Creek|Slough) "
                     r"((?:downstream|upstream|west|east|north|south) of (?:the )?[^.,;]+?)(?=\s+and\s|[.,;]|$)", re.I)
GALLONS = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s+gallons", re.I)
ADVICE = re.compile(r"(?:Avoid contact|advised to|are not advised|advises the public to avoid)", re.I)


# ---------------------------------------------------------------- the feed and the pages

def _tag(blk: str, n: str) -> str:
    x = re.search(rf"(?is)<{n}\b[^>]*>(.*?)</{n}>", blk)
    v = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", x.group(1)) if x else ""
    return re.sub(r"\s+", " ", html.unescape(html.unescape(v))).strip()


def items(body: bytes | str) -> list[dict]:
    """[{title, link, guid, node, pub_date, description}] of the RSS body (no author field exists or is read)."""
    t = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    out = []
    for m in re.finditer(r"(?is)<item\b[^>]*>(.*?)</item>", t):
        blk = m.group(1)
        guid = _tag(blk, "guid")
        node = re.search(r"/node/(\d+)", guid)
        out.append({"title": _tag(blk, "title"), "link": _tag(blk, "link"), "guid": guid,
                    "node": node.group(1) if node else None, "pub_date": _tag(blk, "pubDate"),
                    "description": clean_text(_tag(blk, "description"))})
    return out


def clean_text(s: str) -> str:
    """House numbers, e-mails and telephone numbers out of a string of BES text."""
    return scrub_text(strip_house_numbers(s or ""))


def page_lines(body: bytes | str) -> dict:
    """{published, updated, label, lines} of an advisory page: the <main> text as lines, the article only (cut at the
    contact block, the prevention tips or the about text: CUT_RE), scrubbed."""
    t = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    m = re.search(r"(?is)<main\b.*?</main>", t)
    blk = m.group(0) if m else t
    blk = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", blk)
    raw_lines = [re.sub(r"\s+", " ", html.unescape(x)).strip() for x in re.sub(r"<[^>]+>", "\n", blk).split("\n")]
    raw_lines = [x for x in raw_lines if x]
    out = {"published": None, "updated": None, "label": None, "lines": []}
    skip_next = None
    for i, x in enumerate(raw_lines):
        if i == 0:
            continue                                   # the title (the item's own)
        if skip_next:
            out[skip_next] = x
            skip_next = None
            continue
        low = x.lower().rstrip(":")
        if low in ("published", "updated"):
            skip_next = low
            continue
        if low == "label":
            skip_next = "label"
            continue
        if CUT_RE.match(x):
            break
        if low + ":" in SKIP_LINES or low in SKIP_LINES:
            continue
        out["lines"].append(clean_text(x))
    return out


def body_text(page: dict | None, item: dict) -> str:
    """The advisory's text as one string (the page's lines, else the RSS description); line breaks inside sentences
    (links) are joined."""
    lines = (page or {}).get("lines") or [item.get("description") or ""]
    return re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", " ".join(lines))).strip()


# ---------------------------------------------------------------- times

def local(s: str | None) -> datetime | None:
    """'October 22, 2026 9:30 am' (a page's Published line) -> an aware datetime in Portland."""
    if not s:
        return None
    for f in ("%B %d, %Y %I:%M %p", "%B %d, %Y %I %p", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), f).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def rss_time(s: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(s).astimezone(TZ) if s else None
    except (TypeError, ValueError):
        return None


def clock(t: str | None) -> tuple[int, int] | None:
    """'4:20 pm', '9:01 a.m.', '3:34am', '10 a.m.', 'Midnight', 'noon' -> (hour, minute)."""
    if not t:
        return None
    s = t.strip().lower()
    if s == "midnight":
        return 0, 0
    if s == "noon":
        return 12, 0
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([ap])", s)
    if not m:
        return None
    h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
    return (h + 12 if m.group(3) == "p" else h), mi


def day_of(m: re.Match, ref: datetime, n: str = "") -> datetime | None:
    """The date a match names (Month day[, year] or m/d/yy), the year from the reference when not given (the year
    before when the date would fall more than a day after the reference)."""
    g = m.groupdict()
    if g.get(f"{n}mon"):
        mon, day, year = MONTHS.index(g[f"{n}mon"].lower()) + 1, int(g[f"{n}day"]), g.get(f"{n}year")
    elif g.get(f"{n}m"):
        mon, day, year = int(g[f"{n}m"]), int(g[f"{n}d"]), g.get(f"{n}y")
        if year and len(year) == 2:
            year = "20" + year
    else:
        return None
    try:
        if year:
            return datetime(int(year), mon, day, tzinfo=TZ)
        d = datetime(ref.year, mon, day, tzinfo=TZ)
        return d.replace(year=ref.year - 1) if d > ref + timedelta(days=1) else d
    except ValueError:
        return None


def at(day: datetime, t: str | None) -> datetime | None:
    c = clock(t)
    return day.replace(hour=c[0], minute=c[1]) if c else None


def weekday_before(name: str, ref: datetime) -> datetime:
    """The latest date on or before the reference that falls on this weekday."""
    back = (ref.weekday() - WEEKDAYS.index(name.lower())) % 7
    d = ref - timedelta(days=back)
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def text_day(text: str, ref: datetime) -> tuple[datetime | None, str | None]:
    """The day the text gives for the release, without a time ('On Friday, December 5, City crews', 'Wednesday
    morning', 'first reported on October 18')."""
    for rx, basis in DAY_RULES:
        m = rx.search(text)
        if m:
            d = day_of(m, ref)
            if d:
                return d, basis
    m = WEEKDAY_PART.search(text)
    if m:
        return weekday_before(m.group("wd") or m.group("wd2"), ref), \
            "the weekday the advisory gives, read as the latest such day on or before its publication"
    return None, None


def find_start(text: str, ref: datetime) -> tuple[datetime | None, str, str]:
    """(start, precision, basis): the text's own start, else its day, else the publication time (START_RULES)."""
    t = re.sub(r"\bO(\d)", r"0\1", text)                # "O1:15 am": a letter O typed for a zero
    for rx, basis in START_RULES:
        m = rx.search(t)
        if m:
            d = day_of(m, ref)
            s = at(d, m.group("t")) if d else None
            if s:
                return s, "minute", basis
    day, dbasis = text_day(t, ref)
    for rx, basis in TIME_ONLY_RULES:
        m = rx.search(t)
        if m and day is not None:
            s = at(day, m.group("t"))
            if s:
                return s, "minute", f"{basis}; the day: {dbasis}"
    if day is not None:
        return day, "day", dbasis
    return ref, "minute", ("the advisory gives no start: its publication time, the latest the release can have "
                           "begun")


def find_expiry(text: str, ref: datetime) -> datetime | None:
    t = re.sub(r"\bO(\d)", r"0\1", text)
    for rx in EXPIRY_RULES:
        m = rx.search(t)
        if m:
            d = day_of(m, ref)
            x = at(d, m.group("t")) if d else None
            if x:
                return x
    return None


def find_end(text: str, start: datetime, start_precision: str, ref: datetime) -> tuple[datetime | None, str | None,
                                                                                         str | None]:
    """(end, precision, basis) from the text, or (None, None, None). Never invented (module docstring)."""
    t = re.sub(r"\bO(\d)", r"0\1", text)
    for rx, basis in END_RULES:
        m = rx.search(t)
        if not m:
            continue
        d = day_of(m, ref) if (m.groupdict().get("mon") or m.groupdict().get("m")) else (
            datetime(start.year, start.month, start.day, tzinfo=TZ))
        e = at(d, m.group("t")) if d else None
        if e is not None and e < start and not (m.groupdict().get("mon") or m.groupdict().get("m")):
            e += timedelta(days=1)                       # "stopped at 1 am" after a late-evening start
        if e is not None and e >= start:
            return e, "minute", basis
    m = DURATION.search(t)
    if m and start_precision == "minute":
        n = m.group("n").lower()
        n = int(n) if n.isdigit() else NUMBERS[n]
        dur = timedelta(minutes=n) if m.group("u").lower().startswith("minute") else timedelta(hours=n)
        return start + dur, "minute", f"the start plus the duration the advisory gives ({m.group(0)})"
    if STOPPED.search(t):
        return ref, "bound", ("the advisory says the release has stopped, without a time: its publication time is "
                              "the latest the release can have ended")
    return None, None, None


# ---------------------------------------------------------------- the rest of the record

def waters_of(text: str) -> list[str]:
    out: list[str] = []
    for rx in WATER_RULES:
        for m in rx.finditer(text):
            for k in ("w1", "w2"):
                w = (m.groupdict().get(k) or "").strip()
                w = re.sub(r"^(?:The|A|An)\s+", "", w)
                if w and w not in out:
                    out.append(w)
    return out


def sentences(text: str) -> list[str]:
    """The text's sentences, a page heading run into one ("Public advisory Avoid contact ...") taken off."""
    out = [re.sub(r"^(?:Public [Aa]dvisory:?|About the CSO|Key details)\s+", "", s.strip())
           for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)]
    return [s for s in out if s]


def volume_of(text: str) -> tuple[int | None, str | None, str]:
    figs = list(dict.fromkeys(int(x.replace(",", "")) for x in GALLONS.findall(text)))
    flag = "estimated" if re.search(r"\bestimat|\bapproximately\b", text, re.I) else "unknown"
    if len(figs) == 1:
        return figs[0], None, flag
    if figs:
        return None, "; ".join(s for s in sentences(text) if GALLONS.search(s)), flag
    return None, None, "unknown"


def records_for(it: dict, page: dict | None, fetched_at: str) -> list[dict]:
    """The records of one advisory item (one, or one per release it reports)."""
    text = body_text(page, it)
    pub = local((page or {}).get("published")) or rss_time(it.get("pub_date"))
    upd = local((page or {}).get("updated"))
    ref = pub or rss_time(it.get("pub_date")) or datetime.now(TZ)
    yref = max(x for x in (ref, upd) if x)            # a date the text names is on or before the last update
    again = AGAIN.search(re.sub(r"\bO(\d)", r"0\1", text))
    start, sprec, sbasis = find_start(AGAIN.sub("", text) if again else text, yref)
    if sbasis.startswith("the advisory gives no start"):
        start = ref                                     # the publication, not the update
    title = it.get("title") or ""
    is_cso = bool(CSO_RE.search(title) or CSO_RE.search(text[:400]))
    end, eprec, ebasis = find_end(AGAIN.sub("", text) if again else text, start, sprec, yref)
    expiry = find_expiry(text, yref)
    m48 = ADVICE48.search(text)
    if end is None and expiry is not None and m48:
        # the City never says when the overflow stopped: its expiry less the 48 hours its advice gives is the latest
        # the overflow can have stopped (ended by), so the end is a bound; the window drawn ends at the City's expiry
        end, eprec = expiry - timedelta(hours=48), "bound"
        ebasis = ("ended by this time: the advisory's expiry less the 48 hours after the overflow stops that its advice "
                  "gives (the City does not state the stop); the window drawn ends at the City's own expiry")
    if end is not None and end < start:
        end, eprec, ebasis = None, None, None
    # an authority's advice to avoid a named water, with no end or stop stated, stands until the City ends it: ongoing
    # (red while it runs, then "end not confirmed"), as when the text says the release is ongoing
    avoid = AVOID_WATER.search(text)
    status = "ended" if end is not None else ("ongoing" if ONGOING.search(text) or avoid else "unknown")
    waters = waters_of(text)
    no_water = next((m.group(0).strip() for rx in NO_WATER for m in [rx.search(text)] if m), None)
    private = bool(PRIVATE.search(text))
    vol, vtext, vflag = volume_of(text)
    advice = " ".join(s for s in sentences(text) if ADVICE.search(s) and "tips" not in s.lower())[:600] or None
    stretch = STRETCH.search(text)
    raw = {"state": "OR", "time_zone": TZ.key, "title": title, "node": it.get("node"), "guid": it.get("guid"),
           "rss_pub_date": it.get("pub_date"), "page_read": page is not None,
           "advisory_label": (page or {}).get("label"), "text": text[:4000],
           "_type_basis": ("the advisory calls it a combined sewer overflow (CSO)" if is_cso
                           else "the advisory calls it a sewage release"),
           "start_basis": sbasis, "waters": waters}
    if end is not None:
        raw["ended_at_precision"], raw["end_basis"] = eprec, ebasis
    if expiry is not None:
        raw["advisory_expires_at"] = expiry.isoformat()
    if stretch:
        raw["stretch_text"] = stretch.group(1).strip()
    if no_water and not waters:
        raw["reached_water"], raw["_no_water_reason"] = False, f"the advisory says: \"{no_water}\""
    if status == "ongoing" and avoid and not ONGOING.search(text):
        raw["status_basis"] = (f"the City's advice to avoid the water (\"{avoid.group(0)}\") with no end stated: in "
                               "effect until the City ends it")
    if "and/or" in text and len(waters) > 1:
        raw["waters_note"] = "the City names the waters with \"and/or\"; both are kept (on the safe side)"
    if private:
        raw["private_source"] = True
        raw["operator_note"] = "the advisory says the release came from private property or a private outfall"
    if page is None:
        raw["_page_pending"] = True
    base = dict(
        source_id=SOURCE_ID, event_type="cso" if is_cso else "sso", status=status,
        discharger_id=None if private else DISCHARGER_ID,
        discharger_name=None if private else "City of Portland Environmental Services",
        npdes_permit=CSO_PERMIT if is_cso and not private else None,
        waterbody_text="; ".join(waters) or None, water_match="name" if waters else "none",
        started_at=start.isoformat(), ended_at=end.isoformat() if end else None, time_precision=sprec,
        reported_at=None, published_at=pub.isoformat() if pub else None,
        source_updated_at=upd.isoformat() if upd else None, fetched_at=fetched_at,
        material="sewage" if not is_cso else "combined sewage", volume_gal=vol, volume_text=vtext,
        estimate_flag=vflag, authority=AUTHORITY, advice_text=advice,
        advice_window_hours=48 if m48 else None,
        advice_window_basis=(f"City of Portland Environmental Services: \"{sentence_with(text, m48)}\"" if m48 else None),
        source_url=it.get("link") or FEED)
    recs = [event(source_record_id=it.get("node") or slug(it.get("link")), **base, raw=raw)]
    if again:
        d = day_of(again, yref)
        s2 = at(d, again.group("t")) if d else None
        if s2 and s2 > start:
            raw2 = {**raw, "start_basis": "the second release the same advisory reports (\"and again ...\"): it "
                                          "began at or before this time", "release": 2}
            recs.append(event(source_record_id=f"{it.get('node') or slug(it.get('link'))}-2",
                              **{**base, "started_at": s2.isoformat(), "time_precision": "minute",
                                 # announced in the page's update, not its first publication
                                 "published_at": (upd or pub).isoformat() if (upd or pub) else None}, raw=raw2))
    return recs


def sentence_with(text: str, m: re.Match) -> str:
    for s in sentences(text):
        if m.group(0) in s:
            return s
    return m.group(0)


def slug(s: str | None) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")[-80:]


# ---------------------------------------------------------------- run

def fetch_safe(sess: requests.Session, prev: dict[str, dict]) -> dict:
    """The feed and the pages of the advisories not yet read (or updated since), as the safe document data/raw keeps."""
    r = sess.get(FEED, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    its = items(r.content)
    pages = {}
    for it in its:
        if not TITLE_RE.search(it["title"] or "") or NOT_SEWAGE_TITLE.search(it["title"] or ""):
            continue
        old = prev.get(it.get("node") or "") or {}
        oraw = old.get("raw") or {}
        if oraw.get("guid") == it["guid"] and oraw.get("page_read") and oraw.get("_page"):
            pages[it["node"]] = oraw["_page"]          # unchanged since the last read
            continue
        try:
            p = sess.get(it["link"], headers=HEADERS, timeout=TIMEOUT)
            p.raise_for_status()
            pages[it["node"]] = page_lines(p.content)
        except requests.RequestException:
            pass                                        # read again next run (raw._page_pending)
    return {"format": SAFE_FORMAT, "feed": FEED, "items": its, "pages": pages}


def build(doc: dict, prev_records: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    recs: dict[str, dict] = {r["source_record_id"]: r for r in prev_records}
    read, not_read = 0, []
    for it in doc.get("items") or []:
        if not TITLE_RE.search(it.get("title") or "") or NOT_SEWAGE_TITLE.search(it.get("title") or ""):
            not_read.append(it.get("title"))
            continue
        page = (doc.get("pages") or {}).get(it.get("node") or "")
        old = recs.get(it.get("node") or "")
        if page is None and old and (old.get("raw") or {}).get("page_read"):
            continue                                    # a page read before is kept when this run could not read it
        for r in records_for(it, page, fetched_at):
            if page is not None:
                r["raw"]["_page"] = page                # kept so an unchanged page is not asked for again
            prev = recs.get(r["source_record_id"])
            if prev:
                r["raw"]["_first_seen_at"] = (prev.get("raw") or {}).get("_first_seen_at") or prev.get("fetched_at")
            else:
                r["raw"]["_first_seen_at"] = fetched_at
            r["raw"]["_last_seen_in_source"] = fetched_at
            recs[r["source_record_id"]] = r
            read += 1
    out = sorted(recs.values(), key=lambda r: r.get("started_at") or "", reverse=True)
    stats = {"items": len(doc.get("items") or []), "advisories_read": read, "not_read": len(not_read),
             "records": len(out),
             "by_type": {t: sum(1 for r in out if r["event_type"] == t) for t in ("cso", "sso")},
             "with_window_48h": sum(1 for r in out if r.get("advice_window_hours")),
             "no_water_named": sum(1 for r in out if not r.get("waterbody_text"))}
    return out, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved safe document (data/raw/or-bes-news-rss/*.json) instead of the network")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records") or []
    try:
        if args.file:
            doc = json.loads(Path(args.file).read_text())
            if doc.get("format") != SAFE_FORMAT:
                raise ValueError(f"not a {SAFE_FORMAT} document")
        else:
            sess = requests.Session()
            doc = fetch_safe(sess, {r["source_record_id"]: r for r in prev})
            save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False, indent=1), "json")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    recs, stats = build(doc, prev, fetched_at)
    meta = {**stats, "feed": FEED, "registry_ids": [SOURCE_ID], "timezone": TZ.key,
            "credit": "City of Portland Environmental Services, news (CSO and sewage advisories)",
            "time_basis": ("Published and Updated as each advisory's page gives them (Portland time); the start and end "
                           "as its text gives them (raw.start_basis, raw.end_basis); the RSS pubDate follows the page's "
                           "last update and is never the start")}
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {json.dumps(stats)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
