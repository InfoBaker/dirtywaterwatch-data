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
  The full list read on 2026-11-14: 71 pages, 281 posts since 2016, of which 18 are Storm Updates or overflow letters
  (2018-06-22 to 2026-09-08). The September 3, 2026 overflow was posted September 8; the August 1, 2026 overflow August 6.

Which posts are read
  A post is read when its title names a storm update, an overflow alert or a letter about overflows (TITLE_RE). Every
  other post (budgets, open houses, plant sales, "How MMSD's Deep Tunnel System Operates During Heavy Rain") is not;
  meta.not_read counts them. A follow-up about an earlier storm (an open house, a modelling report) is not a report.

Record rules (rules only: no model, no geocoding)
  - Key: the post's slug plus the overflow type, "<slug>:cso" and "<slug>:sso". A post that reports a combined sewer
    overflow and a separate sewer overflow gives two records.
  - Type (raw._type_basis): cso when the post reports a combined sewer overflow (a labelled volume, "a combined sewer
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
    April 4, 2024"; "ended on March 1st, 2023, at 8:00 am"): raw.ended_at_precision minute, status ended. Otherwise no
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
    operator and placed nowhere. No point: MMSD gives none, and a street in the text is never geocoded.
    raw.keeps_rain_caution: a post never switches off the radar's rain caution on the permit's outfalls.
  - Operator: Milwaukee Metropolitan Sewerage District, permit WI0036820 (its two water reclamation facilities and the
    combined sewer outfalls). The member municipalities' own overflows named in a post are not MMSD's records.
  - The year-to-date "Gallons Overflowed" counter, the Water Drop Alert (a request to use less water before a storm) and
    the deep tunnel's storage are never read as an overflow (MMSD says its counter can be corrected).

History: the list is read two pages deep each run (eight posts, months of news); records already built are carried,
never dropped because a post scrolled off; `--pages 71` reads the whole list. A post is read again when its stamp or
title changes.

Privacy: only each post's title, stamp, letter links and article lines are kept; the article is cut at MMSD's standing
advice block ("Text WATERDROP ...") and telephone numbers and e-mails are scrubbed (common.scrub_text), house numbers
removed (common.strip_house_numbers). data/raw keeps that safe document only.

Failures: a list page that cannot be read writes ok=False and keeps the previous records; a post that cannot be read is
read again next run.

Run from pipeline/:  python -m ingest.wi_mmsd_storm_updates [--pages 2] [--file saved.json]
"""
from __future__ import annotations

import argparse
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
PAUSE_S = 1.5
TIMEOUT = 90
SAFE_FORMAT = "wi-mmsd-storm-updates/1"
TZ = ZoneInfo("America/Chicago")
PERMIT = "WI0036820"
DISCHARGER_ID = "wi-mmsd"
DISCHARGER_NAME = "Milwaukee Metropolitan Sewerage District"
AUTHORITY = "Milwaukee Metropolitan Sewerage District (Storm Update post; operator's report to the DNR)"
MATERIAL = {"cso": "combined sewage and stormwater", "sso": "untreated sewage"}

TITLE_RE = re.compile(r"storm update|overflow alert|letter to (?:the )?dnr about (?:recent )?overflows", re.I)

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
    re.compile(rf"\bstarted\s+(?:at\s+)?(?:approximately\s+)?{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\b(?:around|approximately|at)\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
]
END_RX = [
    re.compile(rf"\bended\s+at\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\bended\s+on\s+(?P<d>{ANY_DATE}),?\s+at\s+{CLOCK}", re.I),
]

TYPE_WORDS = {"cso": re.compile(r"combined sewer overflows?|\bcsos?\b", re.I),
              "sso": re.compile(r"(?:separate|sanitary) sewer overflows?|\bssos?\b", re.I)}
# a sentence about the type in general, a plan, a reduction or capacity: not a report of an overflow
NOT_REPORT = re.compile(r"\b(?:reduc\w*|prevent\w*|risk of|invest\w*|plan\w*|since \d{4}|average|why|how|learn|"
                        r"protect\w*|captured|deep tunnel|storage|capacity|budget|project)\b", re.I)
LOCAL = re.compile(r"local (?:and regional )?sewer systems?|systems? that are owned by municipalities|"
                   r"(?:were|was) reported by|municipal(?:ities|ity)? (?:sewer|system)", re.I)
REPORT_CUE = re.compile(r"\b(?:took place|occurred|occured|occurring|started|initiated|resulted|reporting|reported|"
                        r"regarding|estimated|volume)\b|:\s*\d", re.I)
GENERIC_OVERFLOW = re.compile(r"\b(?:sewer )?overflows?\b", re.I)
VOL = r"(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>million|billion)?\s*gallons"
LABELLED = re.compile(
    r"\b(?P<label>combined sewer overflows?(?:\s+and\s+(?:sanitary|separate)\s+sewer\s+overflows?)?|"
    r"(?:separate|sanitary)\s+sewer\s+overflows?)\s*(?:\((?:cso|sso)s?\))?\s*:?\s*(?:volume\s*)?"
    rf"(?:of\s*|(?:is\s+)?estimated\s+at\s*)?(?:approximately\s*)?{VOL}", re.I)
FIGURE = re.compile(VOL, re.I)
NOT_VOLUME = re.compile(r"\b(?:tunnel|storage|capacity|hold|reduc\w*|per day|a day|/\s*day|equals?|prevented|captured|"
                        r"flood|filled|rate|store|acres)\b", re.I)
WATER_INTO = re.compile(r"\b(?:overflow|discharge|release)\w*\s+(?:\w+\s+){0,3}?(?:in)?to\s+(?:the\s+)?"
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
    letters = []
    for m in re.finditer(r'<a\s[^>]*href="([^"]*download_file[^"]*)"[^>]*>(.*?)</a>', body, re.S | re.I):
        label = _words(re.sub(r"<[^>]+>", " ", m.group(2)))
        if label and {"url": m.group(1), "label": safe_line(label)} not in letters:
            letters.append({"url": m.group(1), "label": safe_line(label)})
    text = re.sub(r"<(?:/?(?:p|div|li|ul|ol|h\d|tr|table|br|hr)\b)[^>]*>", "\n", body, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for raw in text.split("\n"):
        w = _words(raw)
        if not w:
            continue
        if CUT.search(w):
            break
        lines.append(safe_line(w))
    if not lines:
        return None
    stamp = next((x for x in lines[:4] if STAMP.match(x)), None)
    return {"stamp": stamp, "lines": [x for x in lines if x != stamp][:200], "letters": letters[:10]}


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


def _resolve(m: int, d: int, y: int | None, ref: date) -> date | None:
    if y:
        return _mk(y, m, d)
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
            last = _mk(first.year + (1 if m2 < m1 else 0), m2, int(re.sub(r"\D", "", m.group("d2")))) if first else None
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
    parts = re.split(r"(?<=[.!?])(?<!\d\.)\s+(?=[A-Z(])|\n+", t)
    return [_words(p) for p in parts if _words(p)]


def _gal(m: re.Match) -> int:
    n = float(m.group("n").replace(",", ""))
    u = (m.group("u") or "").lower()
    return int(round(n * (1e9 if u == "billion" else 1e6 if u == "million" else 1)))


def read_post(title: str, doc: dict, list_date: str | None = None) -> dict:
    """The facts of one post: published time, period, stated start and end, the types reported, volume and waters
    per type, and the bases."""
    pub = stamp_time(doc.get("stamp"))
    ref = pub.date() if pub else (_list_date(list_date) or date.today())
    lines = doc.get("lines") or []
    body = "\n".join(lines)
    sents = sentences(body)
    lede = " ".join(sents[:3])
    per = period(title, ref) or period(lede, ref)
    facts = {"published": pub, "period": per, "types": {}, "local": [], "start": None, "end": None}
    # the stated start and end (minute)
    for rx in START_RX:
        m = rx.search(body)
        if m:
            d = parse_date(m.group("d"), ref)
            if d:
                facts["start"] = (_at(d, m), m.group(0))
                break
    for rx in END_RX:
        m = rx.search(body)
        if m:
            d = parse_date(m.group("d"), ref)
            if d:
                facts["end"] = (_at(d, m), m.group(0))
                break
    types: dict[str, dict] = {}

    def add(t: str, basis: str) -> dict:
        x = types.setdefault(t, {"basis": basis, "volume": None, "volume_text": None, "covers": None, "waters": []})
        return x

    for s in sents:
        if LOCAL.search(s):
            facts["local"].append(s)
    # labelled volumes first
    for m in LABELLED.finditer(body):
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
        if LOCAL.search(s) or NOT_REPORT.search(s) and not LABELLED.search(s):
            continue
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(s)]
        if len(named) == 1 and REPORT_CUE.search(s):
            x = add(named[0], f"MMSD's post: \"{s[:240]}\"")
            figs = [f for f in FIGURE.finditer(s) if not NOT_VOLUME.search(s[max(0, f.start() - 60):f.end() + 20])]
            if x["volume_text"] is None and len(figs) == 1:
                x["volume"], x["volume_text"] = _gal(figs[0]), _words(figs[0].group(0))
            elif x["volume_text"] is None and not figs:
                # "A separate sewer overflow occurred on June 18 ... The volume is estimated at 3.7 million gallons."
                k = sents.index(s)
                nxt = sents[k + 1] if k + 1 < len(sents) else ""
                m2 = re.match(rf"the volume (?:is|was) estimated at\s*(?:approximately\s*)?{VOL}", nxt, re.I)
                if m2 and not any(rx.search(nxt) for rx in TYPE_WORDS.values()):
                    x["volume"], x["volume_text"] = _gal(m2), _words(m2.group(0))
    # the letters' own labels ("DNR Letter for: Combined Sewer Overflow / Separate Sewer Overflows")
    for let in doc.get("letters") or []:
        for t, rx in TYPE_WORDS.items():
            if rx.search(let.get("label") or ""):
                add(t, f"MMSD's letter to the DNR is labelled \"{let['label']}\"")
    # an unlabelled figure ("Overflow volume of 96 million gallons") belongs to the one type the post reports
    if len(types) <= 1:
        for s in sents:
            if LOCAL.search(s) or NOT_VOLUME.search(s):
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
    if not types and any(GENERIC_OVERFLOW.search(s) for s in sents[:4] + [title]):
        add("sso", "MMSD's post reports sewer overflows without saying they were combined sewer overflows; typed as a "
                   "sanitary sewer overflow, the general case")
    # waters
    for s in sents:
        if LOCAL.search(s):
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
               "letters": doc.get("letters") or [], "keeps_rain_caution": True,
               "text": " ".join(doc.get("lines") or [])[:4000]}
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
        if f["start"] and (t == "cso" or len(f["types"]) == 1):
            start, sprec = f["start"][0].isoformat(), "minute"
            raw["start_basis"] = f"MMSD's post: \"{f['start'][1]}\""
        elif per:
            start, sprec = per[0].isoformat(), "day"
            raw["start_basis"] = f"the first day of the dates the post gives (\"{per[2]}\"); no time of day stated"
        else:
            raw["start_basis"] = "the post states no date for the overflow"
        end = None
        if f["end"] and (t == "cso" or len(f["types"]) == 1) and start:
            if f["end"][0].isoformat() >= start:
                end = f["end"][0].isoformat()
                raw["ended_at_precision"], raw["end_basis"] = "minute", f"MMSD's post: \"{f['end'][1]}\""
        if x["waters"]:
            raw["waters"] = x["waters"]
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

def fetch_safe(sess: requests.Session, pages: int, prev: dict[str, dict]) -> dict:
    items: list[dict] = []
    for n in range(1, pages + 1):
        r = sess.get(LIST_URL, params={PAGE_PARAM: n, **LIST_PARAMS}, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        found = list_items(r.content)
        if not found:
            if n == 1:
                raise RuntimeError("no news items on the first list page (the layout may have changed)")
            break
        items += found
        time.sleep(PAUSE_S)
    docs = {}
    for it in items:
        if not TITLE_RE.search(it["title"]):
            continue
        old = (prev.get(it["slug"]) or {}).get("raw") or {}
        if old.get("_doc") and old.get("title") == it["title"] and old.get("list_date") == it["list_date"]:
            docs[it["slug"]] = old["_doc"]
            continue
        try:
            p = sess.get(it["url"], headers=HEADERS, timeout=TIMEOUT)
            p.raise_for_status()
            d = page_doc(p.content)
            if d:
                docs[it["slug"]] = d
        except requests.RequestException:
            pass
        time.sleep(PAUSE_S)
    return {"format": SAFE_FORMAT, "list_url": LIST_URL, "pages": pages, "items": items, "posts": docs}


def build(doc: dict, prev_records: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    recs: dict[str, dict] = {r["source_record_id"]: r for r in prev_records}
    read, not_read, pending = 0, 0, 0
    for it in doc.get("items") or []:
        if not TITLE_RE.search(it.get("title") or ""):
            not_read += 1
            continue
        post = (doc.get("posts") or {}).get(it["slug"])
        if post is None:
            pending += 1
            continue
        new = records_for(it, post, fetched_at)
        mine = {r["source_record_id"] for r in new}
        for k in [k for k, r in recs.items() if (r.get("raw") or {}).get("slug") == it["slug"] and k not in mine]:
            recs.pop(k)                 # the post no longer reports that type (MMSD edited it)
        for r in new:
            prev = recs.get(r["source_record_id"])
            r["raw"]["_doc"] = post
            r["raw"]["_first_seen_at"] = ((prev or {}).get("raw") or {}).get("_first_seen_at") or fetched_at
            r["raw"]["_last_seen_in_source"] = fetched_at
            recs[r["source_record_id"]] = r
        read += 1
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"items": len(doc.get("items") or []), "posts_read": read, "not_read": not_read, "posts_pending": pending,
             "records": len(out), "by_type": {t: sum(1 for r in out if r["event_type"] == t) for t in ("cso", "sso")},
             "with_volume": sum(1 for r in out if r.get("volume_gal") is not None),
             "with_stated_end": sum(1 for r in out if r.get("ended_at")),
             "water_named": sum(1 for r in out if r.get("waterbody_text")),
             "no_date": sum(1 for r in out if not r.get("started_at"))}
    return out, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", type=int, default=PAGES, help="news list pages to read (71 read the whole list)")
    ap.add_argument("--file", help="a saved safe document (data/raw/wi-mmsd-storm-updates/*.json) instead of the network")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records") or []
    try:
        if args.file:
            doc = json.loads(Path(args.file).read_text())
            if doc.get("format") != SAFE_FORMAT:
                raise ValueError(f"not a {SAFE_FORMAT} document")
        else:
            doc = fetch_safe(requests.Session(), args.pages, {(r.get("raw") or {}).get("slug"): r for r in prev})
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
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {json.dumps(stats)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
