"""Milwaukee Metropolitan Sewerage District (MMSD) Storm Update posts (Wisconsin): the overflows MMSD reports to the
Department of Natural Resources, as dated sewage reports -> data/build/events/wi-mmsd-storm-updates.json

Source
  https://www.mmsd.com/about-us/news (registry: wi-mmsd-storm-updates), MMSD's news list (Concrete CMS page list,
  four posts a page, newest first, `?ccm_paging_p_b23285=<n>`; no RSS), and each Storm Update post under
  /about-us/news/<slug>. After a sewer overflow from its regional system MMSD posts what it reported to the Department
  of Natural Resources, with the overflow's dates, its volume and a link to the letter (the "5-day letter", a PDF that
  is often a scanned image and is not read here). The posts are MMSD's own words: an operator's report, not a verdict
  on the water. The duty behind them: s. NR 210.21(5), Wis. Adm. Code (public notice of every overflow "promptly") and,
  for the combined sewer outfalls, 40 CFR 122.38 (Great Lakes Basin notice within four hours, which MMSD meets by other
  channels if at all: the post itself comes with the letter, five days or so after the overflow).
  The full list read on 2026-11-14: 71 pages, 281 posts since 2016, of which 21 are read: 18 Storm Updates or overflow
  letters and 3 spill or release notices (2018-06-22 to 2026-09-08), giving 29 records (13 cso, 14 sso, 2 plant_bypass).
  The September 3, 2026 overflow was posted September 8; the August 1, 2026 overflow August 6.

Which posts are read
  A post is read when its title names a storm update, an overflow alert, a letter about overflows, a sewer release or
  overflow, or a wastewater or treatment plant spill (TITLE_RE), and is not a budget, programme, project or award
  (NOT_TITLE): candidate(). Every other post (budgets, open houses, plant sales, "How MMSD's Deep Tunnel System Operates
  During Heavy Rain") is not read and is not kept, not even its title. A follow-up about an earlier storm (an open
  house, a modelling report) is not a report. A sentence is a report only when it carries a report cue (occurred,
  took place, started, began, reported, a labelled figure) and no denial, hedge, forecast or prevention (NEGATED: "No
  combined sewer overflow occurred", "may occur", "prevented"); a labelled zero ("0 gallons") is no report.

Record rules (rules only: no model, no geocoding)
  - Key: the post's slug plus the overflow type, "<slug>:cso" and "<slug>:sso". A post that reports a combined sewer
    overflow and a separate sewer overflow gives two records.
  - Type (raw._type_basis): plant_bypass for a spill at a treatment plant ("Treatment Plant Spill", "wastewater
    spill"); a "sanitary sewer release" is sso. cso when the post reports a combined sewer overflow (a labelled volume, "a combined sewer
    overflow that took place / occurred / started", "initiated a combined sewer overflow", a letter labelled Combined
    Sewer Overflow); sso when it reports a separate or sanitary sewer overflow from MMSD's system (the same cues; a
    sentence about overflows "in local sewer systems" of the member municipalities is theirs, not MMSD's, and is kept
    as raw.local_overflows_text only). A post that says only "sewer overflows" is typed sso (a sewer overflow not said to
    come from a combined sewer outfall) with the basis stated, never left unknown.
  - Times, America/Chicago (Milwaukee; raw.time_zone): the post's own stamp ("08/06/26 09:00:am") is published_at.
    reported_at stays null (the post gives the letter's subject, not its receipt date). started_at: a stated start
    ("started at 5:55 pm on April 2, 2024"; "around 10:00 a.m. on 9-3-26"), precision minute; else the first day of the
    dates the title or the opening sentence gives ("August 1st, 2026", "Aug 9-10, 2025", "April 1 thru 4, 2024",
    "February 27 to March 1st, 2023", "8-20-18", "starting on 3/14/2019"), precision day; a date with no year takes the
    post's year, or the year before when that would put it after the post. The last day of a stated range is kept as
    raw.period_end (the storm's dates, never the overflow's end). ended_at only from a stated end ("ended at 8:10 pm on
    April 4, 2024"; "ended on March 1st, 2023, at 8:00 am"; "began on January 6 at around 11:25 PM and continued until
    2:22 AM on January 7, 2026"): raw.ended_at_precision minute, status ended. A stated time belongs to the overflow its
    own sentence names; a sentence naming none gives it only when the post reports one type. A date with no year in a
    post with no stamp and no list date stays unknown (never the reading machine's year). Otherwise no
    end (status unknown): data/rules.json unresolved.day_start_caution gives the site's 72-hour caution from the start
    of the day, then "end not confirmed".
  - Volume: the post's own figure for that type: a labelled one ("Combined Sewer Overflow: 357 Million Gallons",
    "Separate Sewer Overflows (SSO): 4.93 million gallons") or the one figure in a sentence about that type's overflow
    ("The combined sewer overflow volume is estimated at 360 million gallons", "Overflow volume of 96 million gallons"
    when the post reports one type); never a tunnel's capacity, storage, a rate, a reduction or a rainfall equivalent.
    A figure given for both types together ("Combined Sewer Overflow and Sanitary Sewer Overflow: 5.14 billion gallons")
    is kept as volume_text on the cso record with raw.volume_covers both, volume_gal null. MMSD's figures are estimates
    (estimate_flag estimated).
  - Water: the waters a sentence about MMSD's overflow names ("overflow into Lincoln Creek"; "– Wilson Park Creek:
    125,000 gallons" in a list of separate sewer overflows), as waterbody_text. A combined sewer overflow that names no
    water is placed by data/rules.json placement.no_outfall_all_waters on every water the permit's registry outfalls
    discharge to; one that names a water is placed on it with the permit's outfalls on that water
    (build/status.py NAMED_WATER_OUTFALL_STATES). A separate sewer overflow that names no water is listed with the
    operator and placed nowhere. A post that says the sewage reached no water ("No wastewater entered Lake Michigan or
    nearby rivers") keeps raw.reached_water false with the sentence: listed, placed on no water. Every record carries
    raw.county Milwaukee, so a name is placed only on a record reaching Milwaukee County (status.py COUNTY_FIELD_STATES).
    No point: MMSD gives none, and a street in the text is never geocoded.
    raw.keeps_rain_caution: a post never switches off the radar's rain caution on the permit's outfalls.
  - Operator: Milwaukee Metropolitan Sewerage District, permit WI0036820 (its two water reclamation facilities and the
    combined sewer outfalls). The member municipalities' own overflows named in a post are not MMSD's records.
  - The year-to-date "Gallons Overflowed" counter, the Water Drop Alert (a request to use less water before a storm) and
    the deep tunnel's storage are never read as an overflow (MMSD says its counter can be corrected).

Health: a post that cannot be read (a refused connection, an HTTP error, a page with no stamp or no text: an error or
holding page) is not a revision: its records stand, it is listed in meta.retry and read again next run, and the run's
error names it. Every known post is read again REVALIDATE_DAYS after its last read, wherever it is in the list, so a
corrected volume or end is found.
History: the first run (no events file) reads the whole list (BACKFILL_PAGES, stopping at the first empty or repeated
page); later runs read two pages (eight posts, months of news); records already built are carried, never dropped
because a post scrolled off. A post is read again when its stamp or
title changes.

Privacy: only the candidate posts' list items (titles scrubbed) and each one's stamp, letter links and article lines are
kept; the article is cut at MMSD's standing advice block ("Text WATERDROP ...") or at a contact line ("Questions:",
"Media contact"), so the people named there are never kept, and telephone numbers and e-mails are scrubbed (common.scrub_text), house numbers
removed (common.strip_house_numbers). data/raw keeps that safe document only.

Failures: a list page that cannot be read writes ok=False and keeps the previous records; a post that cannot be read is
read again next run.

Run from pipeline/:  python -m ingest.wi_mmsd_storm_updates [--pages 2] [--file saved.json]
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, strip_house_numbers, write_events

SOURCE_ID = "wi-mmsd-storm-updates"
BASE = "https://www.mmsd.com"
LIST_URL = BASE + "/about-us/news"
PAGE_PARAM = "ccm_paging_p_b23285"
LIST_PARAMS = {"ccm_order_by_b23285": "cv.cvDatePublic", "ccm_order_by_direction_b23285": "desc"}
PAGES = 2
BACKFILL_PAGES = 90         # the first run (no events file yet) reads the whole list: 71 pages on 2026-11-14
PAUSE_S = 1.5
TIMEOUT = 90
SAFE_FORMAT = "wi-mmsd-storm-updates/1"
TZ = ZoneInfo("America/Chicago")
PERMIT = "WI0036820"
DISCHARGER_ID = "wi-mmsd"
DISCHARGER_NAME = "Milwaukee Metropolitan Sewerage District"
AUTHORITY = "Milwaukee Metropolitan Sewerage District (Storm Update post; operator's report to the DNR)"
MATERIAL = {"cso": "combined sewage and stormwater", "sso": "untreated sewage",
            "plant_bypass": "wastewater at a treatment plant"}
REVALIDATE_DAYS = 30        # a known post is read again this long after its last read (a corrected volume or end)

TITLE_RE = re.compile(r"storm update|overflow alert|letter to (?:the )?dnr about (?:recent )?overflows|"
                      r"sewer (?:release|overflow)|(?:wastewater|sewage) spill|treatment plant spill|"
                      r"(?:sewage|wastewater) release", re.I)
# budgets, projects and programmes that name overflows in their titles are not reports
NOT_TITLE = re.compile(r"budget|proposed|reduc\w*|program|project|plant sale|award|approves|priorit", re.I)

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12}
MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|" \
      r"nov(?:ember)?|dec(?:ember)?)\.?"
DAY = r"\d{1,2}(?:st|nd|rd|th)?(?!\d)"
SEP = r"\s*(?:-|–|—|thru|through|to|&|and|,)\s*"
DATE_RANGE = re.compile(rf"\b(?P<m1>{MON})\s+(?P<d1>{DAY})(?:{SEP}(?:(?P<m2>{MON})\s+)?(?P<d2>{DAY}))?"
                        rf"(?:,?\s+(?P<y>(?:19|20)\d\d))?\b", re.I)
NUM_DATE = re.compile(r"(?<![\d/.-])(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?![\d/])")
STAMP = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{2})\s+(\d{1,2}):(\d{2}):?\s*([ap])\.?m\.?\s*$", re.I)
CLOCK = r"(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>[ap])\.?\s*m\.?"
ANY_DATE = rf"(?:{MON}\s+{DAY}(?:,?\s+(?:19|20)\d\d)?|\d{{1,2}}[/-]\d{{1,2}}[/-](?:\d{{4}}|\d{{2}}))"
START_RX = [
    re.compile(rf"\bbegan\s+on\s+(?P<d>{ANY_DATE})\s+at\s+(?:around\s+|approximately\s+)?{CLOCK}", re.I),
    re.compile(rf"\bstarted\s+(?:at\s+)?(?:approximately\s+)?{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\b(?:around|approximately|at)\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
]
END_RX = [
    re.compile(rf"\buntil\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\bended\s+at\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\bended\s+on\s+(?P<d>{ANY_DATE}),?\s+at\s+{CLOCK}", re.I),
]

TYPE_WORDS = {"cso": re.compile(r"combined sewer overflows?|\bcsos?\b", re.I),
              "sso": re.compile(r"(?:separate|sanitary) sewer overflows?|\bssos?\b|(?:sanitary )?sewer release|"
                                r"sewage release", re.I),
              "plant_bypass": re.compile(r"treatment plant (?:wastewater )?spill|wastewater spill", re.I)}
# a statement that something did not happen, might happen or was prevented is not a report of an overflow
# "May 1, 2027" is a month, not a modal (Astra re-review 2026-11-15 P1-1)
NEGATED = re.compile(r"\b(?:no|not|never|without|zero|none|neither|nor|if|unless|may(?!,?\s+\d)|might|could|would|"
                     r"should|shall|will|possible|potential|potentially|forecast\w*|expected|scheduled|anticipated|"
                     r"projected|avoid\w*|prevent\w*)\b", re.I)
# a sentence is read clause by clause: "a combined sewer overflow occurred ..., but no separate sewer overflow occurred"
# reports the first and denies the second (Astra re-review 2026-11-15 P1-1)
CLAUSE = re.compile(r",?\s+(?:but|however,?|whereas|while)\s+|;\s*|,?\s+and\s+(?=(?:no|not|there was no|there were no)\b)",
                    re.I)
# the post says the sewage reached no water ("No wastewater entered Lake Michigan or nearby rivers")
NO_WATER = re.compile(r"\bno (?:wastewater|sewage|overflow)\b[^.]{0,40}\b(?:entered|reached|went into|flowed into)\b[^.]*", re.I)
# contact and media lines: the people named in them are not kept
CONTACT = re.compile(r"^\s*(?:questions|contact|media contact|press contact|for more information|for media)\b", re.I)
# a sentence about the type in general, a plan, a reduction or capacity: not a report of an overflow
NOT_REPORT = re.compile(r"\b(?:reduc\w*|prevent\w*|risk of|invest\w*|plan\w*|since \d{4}|average|why|how|learn|"
                        r"protect\w*|captured|deep tunnel|storage|capacity|budget|project)\b", re.I)
LOCAL = re.compile(r"local (?:and regional )?sewer systems?|systems? that are owned by municipalities|"
                   r"(?:were|was) reported by|municipal(?:ities|ity)? (?:sewer|system)", re.I)
REPORT_CUE = re.compile(r"\b(?:took place|occurred|occured|occurring|started|began|led to|spill\w*|initiated|resulted|"
                        r"reporting|reported|"
                        r"regarding|estimated|volume)\b|:\s*\d", re.I)
SPILL_CUE = re.compile(r"\b(?:spill\w*|releas\w*|discharg\w*|overflow\w*)\b", re.I)
GENERIC_OVERFLOW = re.compile(r"\b(?:sewer )?overflows?\b", re.I)
VOL = r"(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>million|billion)?\s*gallons"
LABELLED = re.compile(
    r"\b(?P<label>combined sewer overflows?(?:\s+and\s+(?:sanitary|separate)\s+sewer\s+overflows?)?|"
    r"(?:separate|sanitary)\s+sewer\s+overflows?)\s*(?:\((?:cso|sso)s?\))?\s*:?\s*(?:volume\s*)?"
    rf"(?:of\s*|(?:is\s+)?estimated\s+at\s*)?(?:approximately\s*)?{VOL}", re.I)
FIGURE = re.compile(VOL, re.I)
NOT_VOLUME = re.compile(r"\b(?:tunnel|storage|capacity|hold|reduc\w*|per day|a day|/\s*day|equals?|prevented|captured|"
                        r"flood|filled|rate|store|acres)\b", re.I)
WATER_INTO = re.compile(r"\b(?:overflow|discharge|release)\w*\s+(?:[\w-]+\s+){0,3}?(?:in)?to\s+(?:the\s+)?"
                        r"(?P<w>(?:[A-Z][a-z]+\s+){1,3}(?:Creek|River|Harbor|Canal)|Lake Michigan)\b")
WATER_LISTED = re.compile(r"[–—-]\s*(?P<w>(?:[A-Z][a-z]+\s+){1,3}(?:Creek|River|Harbor|Canal)|Lake Michigan)\s*:\s*"
                          r"\d[\d,]*(?:\.\d+)?\s*(?:million\s+)?gallons")
CUT = re.compile(r"^\s*(?:Text WATERDROP|Receive Water Drop Alert|×\s*$)", re.I)


# ---------------------------------------------------------------- pages

def _words(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "").replace("\xa0", " ")).strip()


def list_items(content: bytes | str) -> list[dict]:
    """[{url, slug, title, list_date}] from a news list page."""
    h = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    out = []
    for m in re.finditer(r'ccm-block-page-list-title">\s*<a href="([^"]+)"[^>]*>\s*<h3>(.*?)</h3>\s*</a>.*?'
                         r'ccm-block-page-list-date">(.*?)</div>', h, re.S):
        url = m.group(1)
        if "/about-us/news/" not in url:
            continue
        out.append({"url": url, "slug": slug_of(url), "title": _words(re.sub(r"<[^>]+>", " ", m.group(2))),
                    "list_date": _words(m.group(3))})
    return out


def slug_of(url: str) -> str:
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


DATE_GLUE = re.compile(rf"\b({MON})\s+(?=\d)", re.I)


def safe_line(s: str) -> str:
    """Phones and e-mails scrubbed, house numbers removed; a month's day ("June 18 at 35th St.") is not a house number."""
    glued = DATE_GLUE.sub(lambda m: m.group(1) + "\u2060_", s)
    return strip_house_numbers(scrub_text(glued)).replace("\u2060_", " ")


def page_doc(content: bytes | str) -> dict | None:
    """{stamp, lines, letters} of a post: the article from its title to MMSD's standing advice block, as lines."""
    h = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    i = h.find("ccm-block-page-title")
    if i < 0:
        return None
    body = h[h.rfind("<", 0, i):]
    j = body.find("<footer")
    body = body[:j] if j > 0 else body
    body = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", body, flags=re.S | re.I)
    # one boundary for text and links alike: blocks are read in order and nothing after the cut is kept, a letter's
    # link label included (Astra review 2026-11-14 P1-6)
    letters, lines = [], []
    for block in re.split(r"<(?:/?(?:p|div|li|ul|ol|h\d|tr|table|br|hr)\b)[^>]*>", body, flags=re.I):
        w = _words(re.sub(r"<[^>]+>", " ", block))
        if not w:
            continue
        if CUT.search(w) or CONTACT.search(w):
            break                       # MMSD's standing advice block, or a contact block naming people
        for m in re.finditer(r'<a\s[^>]*href="([^"]*download_file[^"]*)"[^>]*>(.*?)</a>', block, re.S | re.I):
            label = safe_line(_words(re.sub(r"<[^>]+>", " ", m.group(2))))
            if label and {"url": m.group(1), "label": label} not in letters:
                letters.append({"url": m.group(1), "label": label})
        lines.append(safe_line(w))
    stamp = next((x for x in lines[:4] if STAMP.match(x)), None)
    body = [x for x in lines if x != stamp]
    # a post is read only when it has its stamp and a line of text below its title: an error or holding page that
    # keeps the title container ("Temporarily unavailable") is not a revision of the post (Astra review P1-3)
    if stamp is None or len(body) < 2:
        return None
    return {"stamp": stamp, "lines": body[:200], "letters": letters[:10]}


# ---------------------------------------------------------------- dates

def _year(y: str | None, ref: date) -> int | None:
    if not y:
        return None
    y = int(y)
    return y + 2000 if y < 100 else y


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _resolve(m: int, d: int, y: int | None, ref: date | None) -> date | None:
    if y:
        return _mk(y, m, d)
    if ref is None:
        return None                     # no year in the text and no dated post to take it from: unknown
    x = _mk(ref.year, m, d)
    if x and x > ref:
        x = _mk(ref.year - 1, m, d)
    return x


def parse_date(text: str, ref: date) -> date | None:
    m = NUM_DATE.fullmatch(text.strip())
    if m:
        return _resolve(int(m.group(1)), int(m.group(2)), _year(m.group(3), ref), ref)
    m = DATE_RANGE.match(text.strip())
    if m:
        return _resolve(MONTHS[m.group("m1")[:3].lower()], int(re.sub(r"\D", "", m.group("d1"))),
                        _year(m.group("y"), ref), ref)
    return None


def period(text: str, ref: date) -> tuple[date, date | None, str] | None:
    """(first day, last day or None, the words) of the first date or range in text."""
    hits = []
    for m in DATE_RANGE.finditer(text):
        y = _year(m.group("y"), ref)
        m1 = MONTHS[m.group("m1")[:3].lower()]
        d1 = int(re.sub(r"\D", "", m.group("d1")))
        first = _resolve(m1, d1, y, ref)
        last = None
        if m.group("d2"):
            m2 = MONTHS[m.group("m2")[:3].lower()] if m.group("m2") else m1
            last = (_mk(first.year + (1 if m2 < m1 else 0), m2, int(re.sub(r"\D", "", m.group("d2"))))
                    if first else None)
        if first:
            hits.append((m.start(), first, last, m.group(0)))
    for m in NUM_DATE.finditer(text):
        first = _resolve(int(m.group(1)), int(m.group(2)), _year(m.group(3), ref), ref)
        if first:
            hits.append((m.start(), first, None, m.group(0)))
    if not hits:
        return None
    _, first, last, words = min(hits, key=lambda h: h[0])
    if last is not None and last < first:
        last = None
    return first, last, words.strip()


def _at(d: date, m: re.Match) -> datetime:
    hh = int(m.group("h")) % 12 + (12 if m.group("ap").lower() == "p" else 0)
    return datetime(d.year, d.month, d.day, hh, int(m.group("mi") or 0), tzinfo=TZ)


def stamp_time(stamp: str | None) -> datetime | None:
    m = STAMP.match(stamp or "")
    if not m:
        return None
    hh = int(m.group(4)) % 12 + (12 if m.group(6).lower() == "p" else 0)
    try:
        return datetime(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)), hh, int(m.group(5)), tzinfo=TZ)
    except ValueError:
        return None


# ---------------------------------------------------------------- text

def sentences(text: str) -> list[str]:
    """Sentences and lines; a decimal point, 'a.m.', 'St.' and 'Ave.' do not end one."""
    t = re.sub(r"\b([ap])\.m\.", r"\1m", text)
    t = re.sub(r"\b(St|Ave|No|Dr|Mt|U\.S)\.", r"\1", t)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])|\n+", t)
    return [_words(p) for p in parts if _words(p)]


def clauses(sentence: str) -> list[str]:
    """A sentence's clauses: each is read on its own for occurrence, denial and times."""
    return [c.strip() for c in CLAUSE.split(sentence) if c and c.strip()]


def _gal(m: re.Match) -> int:
    n = float(m.group("n").replace(",", ""))
    u = (m.group("u") or "").lower()
    return int(round(n * (1e9 if u == "billion" else 1e6 if u == "million" else 1)))


def read_post(title: str, doc: dict, list_date: str | None = None) -> dict:
    """The facts of one post: published time, period, stated start and end, the types reported, volume and waters
    per type, and the bases."""
    pub = stamp_time(doc.get("stamp"))
    ref = pub.date() if pub else _list_date(list_date)     # never the clock of the machine reading it
    # the title repeated as the article's first line is not evidence: a stamped holding page keeps it, and a spill
    # title would otherwise report itself (Astra re-review 2026-11-15 P1-1, P1-4)
    tkey = _words(title).lower()
    lines = [x for x in doc.get("lines") or [] if _words(x).lower() != tkey]
    body = "\n".join(lines)
    sents = [c for x in sentences(body) for c in clauses(x)]
    lede = " ".join(sents[:3])
    per = period(title, ref) or period(lede, ref)
    facts = {"published": pub, "period": per, "types": {}, "local": [], "no_water": None}
    types: dict[str, dict] = {}

    def affirmative(x: str) -> bool:
        """A sentence that reports an overflow: a report cue, no denial, hedge, plan or prevention."""
        return (bool(REPORT_CUE.search(x)) and not NEGATED.search(x) and not LOCAL.search(x)
                and not any(_gal(z) == 0 for z in LABELLED.finditer(x)))

    def add(t: str, basis: str) -> dict:
        x = types.setdefault(t, {"basis": basis, "volume": None, "volume_text": None, "covers": None, "waters": [],
                                 "start": None, "end": None, "day": None})
        return x

    for s in sents:
        if LOCAL.search(s):
            facts["local"].append(s)
    # labelled volumes first
    for m in (m for x in sents if not NEGATED.search(x) and not LOCAL.search(x) for m in LABELLED.finditer(x)):
        if _gal(m) == 0:
            continue                    # "0 gallons": a stated zero is not a report
        label = m.group("label").lower()
        both = " and " in label
        t = "cso" if label.startswith("combined") else "sso"
        if both:
            y = add("sso", f"MMSD's labelled figure: \"{_words(m.group(0))}\"")
            y["covers"] = y["covers"] or "combined and separate sewer overflows together (the figure is on the cso record)"
        x = add(t, f"MMSD's labelled figure: \"{_words(m.group(0))}\"")
        if x["volume_text"] is None:
            x["volume_text"] = _words(m.group(0))
            if both:
                x["covers"] = "combined and separate sewer overflows together"
            else:
                x["volume"] = _gal(m)
    # sentences reporting a type
    for s in sents:
        if LOCAL.search(s) or NOT_REPORT.search(s) and not LABELLED.search(s) \
                or any(_gal(z) == 0 for z in LABELLED.finditer(s)):
            continue
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(s)]
        if len(named) == 1 and affirmative(s):
            x = add(named[0], f"MMSD's post: \"{s[:240]}\"")
            figs = [f for f in FIGURE.finditer(s) if not NOT_VOLUME.search(s[max(0, f.start() - 60):f.end() + 20])]
            if x["volume_text"] is None and len(figs) == 1:
                x["volume"], x["volume_text"] = _gal(figs[0]), _words(figs[0].group(0))
            elif x["volume_text"] is None and not figs:
                # "A separate sewer overflow occurred on June 18 ... The volume is estimated at 3.7 million gallons."
                k = sents.index(s)
                nxt = sents[k + 1] if k + 1 < len(sents) else ""
                figs2 = [f for f in FIGURE.finditer(nxt) if not NOT_VOLUME.search(nxt[max(0, f.start() - 60):f.end() + 20])]
                if len(figs2) == 1 and not NEGATED.search(nxt) and not any(rx.search(nxt) for rx in TYPE_WORDS.values()):
                    x["volume"], x["volume_text"] = _gal(figs2[0]), _words(figs2[0].group(0))
    # a spill or release post whose title names it ("Treatment Plant Spill January 7, 2026")
    # only when the article itself reports a spill or release (a title alone is no evidence: "No wastewater spill
    # occurred" or a holding page makes no record; Astra re-review 2026-11-15 P1-1, P1-4)
    body_says = next((x for x in sents if affirmative(x) and SPILL_CUE.search(x)), None)
    for t in ("plant_bypass", "sso"):
        if TYPE_WORDS[t].search(title) and not NEGATED.search(title) and not types and body_says:
            add(t, f"MMSD's post is titled \"{title}\" and reports: \"{body_says[:240]}\"")
    # the letters' own labels ("DNR Letter for: Combined Sewer Overflow / Separate Sewer Overflows")
    reported = any(affirmative(x) and (GENERIC_OVERFLOW.search(x) or any(r.search(x) for r in TYPE_WORDS.values()))
                   for x in sents[:6])
    for let in doc.get("letters") or [] if reported else []:
        for t, rx in TYPE_WORDS.items():
            if rx.search(let.get("label") or ""):
                add(t, f"MMSD's letter to the DNR is labelled \"{let['label']}\"")
    # an unlabelled figure ("Overflow volume of 96 million gallons") belongs to the one type the post reports
    if len(types) <= 1:
        for s in sents:
            if LOCAL.search(s) or NOT_VOLUME.search(s) or NEGATED.search(s):
                continue
            m = re.search(rf"overflow volume (?:of|was|is)?\s*(?:approximately\s*)?{VOL}", s, re.I)
            if m:
                t = next(iter(types), None)
                if t is None:
                    t = "sso"
                x = add(t, f"MMSD's post: \"{s[:240]}\"")
                if x["volume_text"] is None:
                    x["volume"], x["volume_text"] = _gal(m), _words(m.group(0))
                break
    if not types and any(GENERIC_OVERFLOW.search(x) and affirmative(x) for x in sents[:4]):
        add("sso", "MMSD's post reports sewer overflows without saying they were combined sewer overflows; typed as a "
                   "sanitary sewer overflow, the general case")
    # waters (never from a denial: "No overflow into Example Creek occurred")
    for s in sents:
        if LOCAL.search(s) or NEGATED.search(s):
            continue
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(s)]
        for rx in (WATER_INTO, WATER_LISTED):
            for m in rx.finditer(s):
                w = _words(m.group("w"))
                t = named[0] if len(named) == 1 else ("sso" if rx is WATER_LISTED and "sso" in types else
                                                       next(iter(types), None))
                if t in types and w not in types[t]["waters"]:
                    types[t]["waters"].append(w)
    # a listed water after a "Separate Sewer Overflows" label belongs to the separate sewer overflows
    if "sso" in types:
        tail = body[LABELLED.search(body).start():] if LABELLED.search(body) else ""
        k = re.search(r"(?:separate|sanitary) sewer overflows?", tail, re.I)
        if k:
            for m in WATER_LISTED.finditer(tail[k.start():]):
                w = _words(m.group("w"))
                if w not in types["sso"]["waters"]:
                    types["sso"]["waters"].append(w)
                for t in ("cso",):
                    if t in types and w in types[t]["waters"]:
                        types[t]["waters"].remove(w)
    # stated starts and ends, each given to the overflow its own sentence names (Astra review P1-2): a sentence naming
    # one type gives that type its times; one naming none gives them only when the post reports a single type
    for x in sents:
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(x) and t in types]
        owners = named if len(named) == 1 else ([next(iter(types))] if not named and len(types) == 1 else [])
        if NEGATED.search(x):
            continue                    # an expected, conditional or denied time is not a stated one (Astra P1-3)
        for t in owners:
            if types[t].get("day") is None and len(named) == 1 and affirmative(x):
                d = period(x, ref)
                if d:
                    types[t]["day"] = (d[0], d[2])      # the day the sentence about this overflow gives
            for key, rxs in (("start", START_RX), ("end", END_RX)):
                if types[t][key]:
                    continue
                for rx in rxs:
                    m = rx.search(x)
                    d = parse_date(m.group("d"), ref) if m else None
                    if d:
                        types[t][key] = (_at(d, m), m.group(0))
                        break
    for x in sents:
        nw = NO_WATER.search(x)
        if nw:
            named = [t for t, rx in TYPE_WORDS.items() if rx.search(x) and t in types]
            owners = named or (list(types) if len(types) == 1 else [])
            for t in owners:
                types[t]["no_water"] = _words(nw.group(0))
    facts["types"] = types
    return facts


def _list_date(s: str | None) -> date | None:
    try:
        return datetime.strptime(_words(s), "%b %d, %Y, %I:%M %p").date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- records

def records_for(item: dict, doc: dict, fetched_at: str) -> list[dict]:
    f = read_post(item["title"], doc, item.get("list_date"))
    pub = f["published"]
    per = f["period"]
    out = []
    for t, x in sorted(f["types"].items()):
        raw = {"state": "WI", "time_zone": TZ.key, "county": "Milwaukee", "title": item["title"], "slug": item["slug"],
               "stamp": doc.get("stamp"), "list_date": item.get("list_date"), "_type_basis": x["basis"],
               "letters": doc.get("letters") or [], "keeps_rain_caution": t == "cso"}
        if per:
            raw["period_text"], raw["period_start"] = per[2], per[0].isoformat()
            if per[1]:
                raw["period_end"] = per[1].isoformat()
                raw["period_note"] = "the dates of the storm the post gives; not the overflow's end"
        if f["local"]:
            raw["local_overflows_text"] = " ".join(f["local"])[:600]
        if x["covers"]:
            raw["volume_covers"] = x["covers"]
        start, sprec = None, None
        if x["start"]:
            start, sprec = x["start"][0].isoformat(), "minute"
            raw["start_basis"] = f"MMSD's post: \"{x['start'][1]}\""
        elif x["day"]:
            start, sprec = x["day"][0].isoformat(), "day"
            raw["start_basis"] = f"the date the post's sentence about this overflow gives (\"{x['day'][1]}\")"
        elif per:
            start, sprec = per[0].isoformat(), "day"
            raw["start_basis"] = (f"the first day of the dates the post gives for the storm (\"{per[2]}\"); the post "
                                  "gives no date of its own for this overflow, so it began on or after this day")
        else:
            raw["start_basis"] = "the post states no date for the overflow"
        end = None
        d0 = date.fromisoformat(start[:10]) if start else None
        first = x["start"][0] if x["start"] else (datetime(d0.year, d0.month, d0.day, tzinfo=TZ) if d0 else None)
        if x["end"] and first is not None and x["end"][0] >= first:
            end = x["end"][0].isoformat()
            raw["ended_at_precision"], raw["end_basis"] = "minute", f"MMSD's post: \"{x['end'][1]}\""
        if x["waters"]:
            raw["waters"] = x["waters"]
        if x.get("no_water") and not x["waters"]:
            raw["reached_water"], raw["_no_water_reason"] = False, f"MMSD's post: \"{x['no_water']}\""
        rec = event(
            source_id=SOURCE_ID, source_record_id=f"{item['slug']}:{t}", event_type=t,
            status="ended" if end else "unknown",
            discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER_NAME, npdes_permit=PERMIT,
            waterbody_text="; ".join(x["waters"]) or None, water_match="name" if x["waters"] else "none",
            started_at=start, ended_at=end, time_precision=sprec,
            reported_at=None, published_at=pub.isoformat() if pub else None, source_updated_at=None,
            fetched_at=fetched_at, material=MATERIAL[t], volume_gal=x["volume"], volume_text=x["volume_text"],
            estimate_flag="estimated" if x["volume_text"] else "unknown", authority=AUTHORITY,
            source_url=item["url"], raw=raw,
            parse_error=None if start else "no overflow date found in the post")
        out.append(rec)
    return out


# ---------------------------------------------------------------- run

def candidate(title: str | None) -> bool:
    """A post whose title names a storm update, an overflow letter, or a sewer release or spill (not a budget or a
    programme that names overflows)."""
    return bool(TITLE_RE.search(title or "")) and not NOT_TITLE.search(title or "")


def _stale(raw: dict, fetched_at: str) -> bool:
    try:
        last = datetime.fromisoformat(str(raw.get("_doc_fetched_at")).replace("Z", "+00:00"))
        now = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - last).days >= REVALIDATE_DAYS


def fetch_safe(sess: requests.Session, pages: int, prev: dict[str, dict], retry: list[dict] | None = None,
               fetched_at: str | None = None) -> dict:
    """The safe document: the candidate list items only (titles scrubbed), each candidate post's article, and the
    posts that could not be read (failed). A post is read when it is new, its title or date changed, it failed last
    time (retry), or its last read is REVALIDATE_DAYS old (a corrected volume or end; Astra review P2-8)."""
    fetched_at = fetched_at or now_iso()
    seen: list[dict] = []
    for n in range(1, pages + 1):
        r = sess.get(LIST_URL, params={PAGE_PARAM: n, **LIST_PARAMS}, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        found = list_items(r.content)
        if not found or (seen and found[0]["url"] in {i["url"] for i in seen}):
            if n == 1:
                raise RuntimeError("no news items on the first list page (the layout may have changed)")
            break                       # past the last page (empty, or the CMS repeating a page)
        seen += found
        time.sleep(PAUSE_S)
    items = [{**i, "title": safe_line(i["title"])} for i in seen if candidate(i["title"])]
    have = {i["slug"] for i in items}
    # earlier failures and known posts beyond the pages read (their list item as last kept)
    for extra in list(retry or []) + [{k: (r.get("raw") or {}).get(k2) for k, k2 in
                                       (("url", "url"), ("slug", "slug"), ("title", "title"), ("list_date", "list_date"))}
                                      for r in prev.values()]:
        if extra.get("slug") and extra.get("url") and extra["slug"] not in have:
            items.append(extra)
            have.add(extra["slug"])
    docs, failed = {}, []
    retry_slugs = {x.get("slug") for x in retry or []}
    for it in items:
        old = (prev.get(it["slug"]) or {}).get("raw") or {}
        if old.get("_doc_hash") and old.get("title") == it["title"] and old.get("list_date") == it["list_date"] \
                and it["slug"] not in retry_slugs and not _stale(old, fetched_at):
            continue                    # unchanged and read recently: the record stands as built
        try:
            p = sess.get(it["url"], headers=HEADERS, timeout=TIMEOUT)
            p.raise_for_status()
            d = page_doc(p.content)
            if d:
                docs[it["slug"]] = d
            else:
                failed.append({**it, "reason": "the page has no post stamp or no text (an error or holding page)"})
        except requests.RequestException as e:
            failed.append({**it, "reason": f"{type(e).__name__}"})
        time.sleep(PAUSE_S)
    return {"format": SAFE_FORMAT, "list_url": LIST_URL, "pages": pages, "list_items_seen": len(seen),
            "items": items, "posts": docs, "failed": failed}


def build(doc: dict, prev_records: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    recs: dict[str, dict] = {r["source_record_id"]: r for r in prev_records}
    read, not_read, pending, unparsed = 0, 0, 0, []
    for it in doc.get("items") or []:
        if not candidate(it.get("title")):
            not_read += 1
            continue
        post = (doc.get("posts") or {}).get(it["slug"])
        if post is None:
            # not read this run (unchanged, or it failed): the records built before stand as they were
            pending += 1
            continue
        new = records_for(it, post, fetched_at)
        before = [k for k, r in recs.items() if (r.get("raw") or {}).get("slug") == it["slug"]]
        if not new and before:
            # a stamped page that reports nothing where a report stood (a holding or error page with the title and
            # stamp kept) is not read as a retraction: the records stand and the post is read again (Astra P1-4)
            unparsed.append(it["slug"])
            continue
        mine = {r["source_record_id"] for r in new}
        for k in [k for k, r in recs.items() if (r.get("raw") or {}).get("slug") == it["slug"] and k not in mine]:
            recs.pop(k)                 # a validated post no longer reports that type (MMSD edited it)
        for r in new:
            prev = recs.get(r["source_record_id"])
            r["raw"].update(_doc_hash=hashlib.sha256(json.dumps(post, sort_keys=True).encode()).hexdigest()[:16],
                            url=it["url"], _doc_fetched_at=fetched_at)
            r["raw"]["_first_seen_at"] = ((prev or {}).get("raw") or {}).get("_first_seen_at") or fetched_at
            r["raw"]["_last_seen_in_source"] = fetched_at
            recs[r["source_record_id"]] = r
        read += 1
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"list_items_seen": doc.get("list_items_seen", len(doc.get("items") or [])),
             "candidates": len(doc.get("items") or []), "posts_read": read, "not_read": not_read,
             "posts_not_read_this_run": pending, "posts_failed": len(doc.get("failed") or []),
             "posts_without_report": unparsed,
             "records": len(out),
             "by_type": {t: sum(1 for r in out if r["event_type"] == t) for t in ("cso", "sso", "plant_bypass")},
             "with_volume": sum(1 for r in out if r.get("volume_gal") is not None),
             "with_stated_end": sum(1 for r in out if r.get("ended_at")),
             "water_named": sum(1 for r in out if r.get("waterbody_text")),
             "no_water": sum(1 for r in out if (r.get("raw") or {}).get("reached_water") is False),
             "no_date": sum(1 for r in out if not r.get("started_at"))}
    return out, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", type=int, default=None,
                    help=f"news list pages to read (default {PAGES}; {BACKFILL_PAGES} on a first run, the whole list)")
    ap.add_argument("--file", help="a saved safe document (data/raw/wi-mmsd-storm-updates/*.json) instead of the network")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev_file = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_file.get("records") or []
    retry = (prev_file.get("meta") or {}).get("retry") or []
    try:
        if args.file:
            doc = json.loads(Path(args.file).read_text())
            if doc.get("format") != SAFE_FORMAT:
                raise ValueError(f"not a {SAFE_FORMAT} document")
        else:
            pages = args.pages or (PAGES if prev else BACKFILL_PAGES)
            doc = fetch_safe(requests.Session(), pages, {(r.get("raw") or {}).get("slug"): r for r in prev}, retry,
                             fetched_at)
            save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False, indent=1), "json")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    recs, stats = build(doc, prev, fetched_at)
    meta = {**stats, "list_url": LIST_URL, "registry_ids": [SOURCE_ID], "timezone": TZ.key,
            "credit": "Milwaukee Metropolitan Sewerage District, news (Storm Update posts)",
            "time_basis": ("published_at is the post's own stamp (Milwaukee time); the start and any end are the dates "
                           "and times the post states (raw.start_basis, raw.end_basis); the storm's last day is "
                           "raw.period_end, never the overflow's end")}
    failed = doc.get("failed") or []
    if failed or stats["posts_without_report"]:
        # an incomplete read is not a successful one (Astra review P1-4): ok=False keeps the previous file's records
        # and its last_ok_at; the failed posts are listed for the next run, which reads every post not yet built
        why = "; ".join([f"{f.get('slug')}: {f.get('reason')}" for f in failed] +
                        [f"{x}: a stamped page with no report where one stood" for x in stats["posts_without_report"]])
        retry = [{k: f.get(k) for k in ("url", "slug", "title", "list_date")} for f in failed] + \
                [{k: it.get(k) for k in ("url", "slug", "title", "list_date")} for it in doc.get("items") or []
                 if it.get("slug") in stats["posts_without_report"]]
        write_events(SOURCE_ID, [], ok=False, error=f"posts not read: {why}"[:800], meta={"retry": retry})
        print(f"{SOURCE_ID}: incomplete ({why})", file=sys.stderr)
        return 1
    meta["retry"] = []
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {json.dumps(stats)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
