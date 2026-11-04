"""DC Water news releases and public notices -> sewer overflow notices (source id dc-water-news).

Source
  https://www.dcwater.com/about-dc-water/media/news?page=N (registry: dc-dcwater-news-notices). An HTML
  list, 10 items per page, 0-based, newest first; each item has a date ('16  August,  2025'), a title, a
  linked notice /about-dc-water/media/news/<slug> and the notice's opening paragraphs. No RSS (all
  three feed URLs 404; research/dc/report.md section 2.2). This is the only place DC Water tells the public
  about a large overflow (the Anacostia Force Main in July and August 2025, the Potomac Interceptor
  collapse of 19 January 2026); small creek SSOs and routine CSOs get no notice (nothing in DC law requires
  one). A notice is a statement by DC Water, not a verdict on the water.

What a run does
  Fetches the first three list pages (30 items, about six weeks), keeps the items whose title or summary
  mentions a sewer overflow, sewage, a force main, the Potomac Interceptor, a spill or a public notice
  about water contact, fetches each kept notice, and builds one event per notice that reports a
  discharge. Records already in the events file stay (events scroll off page three; only a new or
  changed notice is rewritten); `--pages N` reads more pages for a backfill, `--dir` replays saved list
  pages (research/dc/raw/news) and notice pages (research/dc/raw/notices) without the network.

  Most kept items are not discharge notices: lane closures for the Interceptor rehabilitation, soil
  removal in the C&O Canal, "no overflows reached the river" updates, community meetings, a notice of a
  possible controlled overflow that was not imminent. An item becomes an event only when one of its
  sentences says an overflow, spill or release occurred or is occurring (not "no overflow", not "may
  occur", not a repair or a plan), and the discharge starts on the notice's date or at most two days
  before it: a later update about an overflow reported earlier is that overflow's follow-up, not a new
  discharge. The counts of kept items that are not events, by reason, are in meta.not_events (dates and
  reasons only; the saved list pages in data/raw/dc-water-news/ hold the rest).

Mapping
  event_id dc-water-news:<notice slug>. event_type sso, cso when the discharge sentence says combined
  sewer overflow. status ongoing when the notice says the overflow is occurring or continues, else
  unknown (never ended: no notice gives an end time in a form we can trust). discharger DC Water
  (DC0021199). started_at from the notice text when it states a date (and an hour when it states one):
  'at approximately 1:40 a.m.' with 'early this morning' on the 16 August notice; else published_at
  with time_precision 'day'. waterbody_text: the DC receiving waters the discharge sentences name
  (ECHO-style aliases normalised to the NHD name, ingest/echo_sewer_overflow_events.py
  DC_WATER_ALIASES; street names such as Anacostia Avenue are not waters). A notice about the Potomac
  Interceptor gets raw.state 'MD' (the pipe is in Maryland and its overflows are reported there,
  docs/decisions.md, Washington DC item 3; the operator stays DC Water). volume from the text when it
  states one figure ('approximately 6,200 gallons', estimate_flag estimated). advice_text: the
  notice's contact advice sentence ('If people come in contact with the untreated overflow ... leave the
  area immediately'), else null. source_url: the notice. No coordinates (a notice names a street).
  Times are naive local (America/New_York), as in the ECHO file.

Duplicates
  An ECHO DC row (data/build/events/echo-sewer-overflow.json, permit DC0021199) whose start-to-end days,
  widened by one day, hold the notice's start date and that names the same water (or whose water the
  notice does not name and is the only such row) is the structured record of the same overflow: the news
  event gets duplicate_of = that row's event_id and sets no colour, so the structured record wins. The
  notice's advice text stays on the news event. Recomputed on every run from the current ECHO file.

Failures
  A list page that cannot be fetched (the first page above all) writes ok=False with the error; the
  previous records stay. A notice that cannot be fetched is built from its list summary, with
  raw.notice_fetched false.

Run from pipeline/:  python -m ingest.dc_water_news [--pages 3] [--dir research/dc/raw]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

from common import (EVENTS_DIR, HEADERS, ROOT, event, now_iso, parse_volume_gal, read_json,
                    save_raw, scrub_text, write_events)

SOURCE_ID = "dc-water-news"
BASE = "https://www.dcwater.com"
LIST_URL = BASE + "/about-dc-water/media/news"
PAGES = 3
PAUSE_S = 1.0
PERMIT = "DC0021199"
DISCHARGER_ID = "dc-dc0021199"
DISCHARGER_NAME = "District of Columbia Water and Sewer Authority (DC Water)"
AUTHORITY = "DC Water (news release / public notice)"
ECHO_FILE = EVENTS_DIR / "echo-sewer-overflow.json"
NEWS_PATH = "/about-dc-water/media/news/"
FOLLOWUP_DAYS = 2        # a discharge that started more than this many days before the notice is reported earlier
MATCH_PAD_DAYS = 1       # ECHO start-to-end days are widened by this to meet the notice's date
MATERIAL = {"sso": "untreated sewage", "cso": "combined sewage and stormwater"}

KEEP = re.compile(r"sewer overflow|sanitary sewer|\bsso\b|\bcso\b|combined sewer|sewage|force main|potomac interceptor|"
                  r"overflow|spill|public notice|water contact|avoid contact|contact with (?:the )?(?:water|river|creek)",
                  re.I)

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTH_RE = "|".join(MONTHS)
DATE_IN_TEXT = re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)
TIME_IN_TEXT = re.compile(r"\b(?:at|about|approximately|around)\s+(?:approximately\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
TODAY_WORDS = re.compile(r"\b(early this morning|this morning|this evening|this afternoon|tonight|today|overnight|earlier today)\b", re.I)
YESTERDAY_WORDS = re.compile(r"\b(last night|yesterday)\b", re.I)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_IN_TEXT = re.compile(r"\b(?:late|early|on)?\s*(" + "|".join(WEEKDAYS) + r")\s+(?:night|evening|morning|afternoon|overnight)\b|"
                             r"\b(?:late|early)\s+(" + "|".join(WEEKDAYS) + r")\b", re.I)
NOTICE_TITLE = re.compile(r"advis\w+|investigat\w+|public notice", re.I)

# a sentence that reports a discharge: an overflow word and an occurrence verb, no negation, hedge or plan
OVERFLOW_WORD = re.compile(r"\b(?:sanitary sewer overflows?|sewer overflows?|sewage overflows?|wastewater overflows?|"
                           r"overflows?|overflowed|overflowing|ssos?|spills?|releases?)\b", re.I)
OCCURRENCE = re.compile(r"\b(?:occurred|occurs|occurring|began|begun|started|observed|discovered|detected|reached|entered|"
                        r"flowed|flowing|overflowed|overflowing|coming|came|experienced|advis(?:ing|es) the public|investigating|"
                        r"continues? to overflow|overflows? continue)\b", re.I)
# an earlier overflow referred to (present perfect, 'where the overflow occurred', 'the overflow that ...')
RETROSPECTIVE = re.compile(r"\b(?:have|has|had)\s+(?:\w+\s+)?(?:occurred|entered|reached|begun|started|overflowed)\b|"
                           r"\b(?:where|when|after|since|before|until)\s+(?:the|an?|this|that)\s+(?:\w+\s+){0,3}(?:overflows?|spills?|releases?|sso)\b|"
                           r"\bthe\s+(?:\w+\s+){0,2}(?:overflows?|spills?|releases?|sso)s?\s+(?:that|which)\b|"
                           r"\b(?:initial|original|previous|earlier|prior|first)\s+(?:\w+\s+)?(?:overflows?|releases?|spills?)\b", re.I)
NOT_OCCURRENCE = re.compile(r"\b(?:no|not|without|never|zero|none|neither|nor|if|may|might|could|would|possible|potential|"
                            r"potentially|prevent\w*|avoid\w*|reduc\w+|control(?:s|led)?|contain\w*|stop(?:s|ped)?|"
                            r"rehabilitat\w+|project|tunnel|plan(?:s|ned)?|expected|forecast\w*|continue to monitor)\b", re.I)
ADVICE = re.compile(r"(?:come in contact|avoid (?:contact|the|these|water)|stay out|should (?:not|take the steps)|do not (?:swim|enter|touch|come)|"
                    r"urges? .{0,40}(?:avoid|stay)|advis\w+ .{0,60}(?:avoid|not to))", re.I)
STREET_WORDS = re.compile(r"\b(?:ave|avenue|street|st|road|rd|parkway|pkwy|drive|dr|boulevard|blvd|bridge|trail|park)\b", re.I)
VOLUME = re.compile(r"((?:approximately|about|an estimated|estimated|roughly|around)\s+)?(\d[\d,]*(?:\.\d+)?)\s*(million\s+)?gallons", re.I)


# ---------------------------------------------------------------- list and notice pages

def _words(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


class ListParser(HTMLParser):
    """Items from a news list page: Drupal `views-row` blocks with a news-date field, a title link to
    /about-dc-water/media/news/<slug> and a body (summary) field. The sidebar's event rows have no
    news-date field and are left out."""

    FIELDS = {"views-field-field-news-date": "date", "views-field-title": "title", "views-field-field-news-body": "summary"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self.depth = 0
        self.row: dict | None = None
        self.row_depth = 0
        self.field: str | None = None
        self.field_depth = 0
        self.href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "br" and self.field == "summary":
            self.row["summary"] += " "
        if tag == "a" and self.field == "title" and self.row is not None:
            self.href = dict(attrs).get("href")
            if self.href:
                self.row["url"] = urljoin(BASE, self.href)
        if tag != "div":
            return
        self.depth += 1
        classes = (dict(attrs).get("class") or "").split()
        if "views-row" in classes and self.row is None:
            self.row, self.row_depth = {"date": "", "title": "", "summary": "", "url": None}, self.depth
        elif self.row is not None and self.field is None:
            for c in classes:
                if c in self.FIELDS:
                    self.field, self.field_depth = self.FIELDS[c], self.depth

    def handle_endtag(self, tag):
        if tag != "div":
            return
        if self.field and self.depth == self.field_depth:
            self.field = None
        if self.row is not None and self.depth == self.row_depth:
            r = self.row
            if r["url"] and NEWS_PATH in r["url"] and r["date"].strip():
                self.items.append({"date_text": _words(r["date"]), "title": _words(r["title"]),
                                   "summary": _words(r["summary"]), "url": r["url"]})
            self.row = None
        self.depth -= 1

    def handle_data(self, data):
        if self.row is not None and self.field:
            self.row[self.field] += data


def parse_list(html: str) -> list[dict]:
    p = ListParser()
    p.feed(html)
    p.close()
    return p.items


class NoticeParser(HTMLParser):
    """The body text of a notice page: the node's field-news-body block, paragraphs and list items as lines."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_body = False
        self.body_depth = 0
        self.skip = 0
        self.lines: list[str] = [""]

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "div":
            self.depth += 1
            if not self.in_body and "field--name-field-news-body" in (dict(attrs).get("class") or "").split():
                self.in_body, self.body_depth = True, self.depth
        if self.in_body and tag in ("p", "li", "br", "tr", "h2", "h3", "h4"):
            self.lines.append("")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == "div":
            if self.in_body and self.depth == self.body_depth:
                self.in_body = False
            self.depth -= 1
        if self.in_body and tag in ("p", "li", "tr"):
            self.lines.append("")

    def handle_data(self, data):
        if self.in_body and not self.skip:
            self.lines[-1] += data


def parse_notice(html: str) -> str:
    p = NoticeParser()
    p.feed(html)
    p.close()
    return "\n".join(x for x in (_words(l) for l in p.lines) if x)


def parse_item_date(text: str) -> date | None:
    """'16  August,  2025' -> 2025-08-16."""
    try:
        return datetime.strptime(_words(text).replace(",", ""), "%d %B %Y").date()
    except ValueError:
        return None


def slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------- reading a notice

DOT = "\u2024"   # a full stop that does not end a sentence, restored after the split


def sentences(text: str) -> list[str]:
    """Sentences and lines; 'a.m.', 'p.m.', 'St.', 'No.', 'U.S.' do not end one."""
    t = re.sub(r"\b([ap])\.m\.", lambda m: f"{m.group(1)}{DOT}m{DOT}", text)
    t = re.sub(r"\b(St|No|Ave|Dr|Mr|Ms|Mrs|U\.S|Md|D\.C|Jan|Feb|Aug|Sept|Oct|Nov|Dec)\.", lambda m: m.group(1) + DOT, t)
    parts = re.split(r"(?<=[.!?])\s+|\n+", t)
    return [_words(p).replace(DOT, ".") for p in parts if _words(p)]


def occurrence_sentences(text: str) -> list[str]:
    out = []
    for s in sentences(text):
        if OVERFLOW_WORD.search(s) and OCCURRENCE.search(s) and not NOT_OCCURRENCE.search(s) and not RETROSPECTIVE.search(s):
            out.append(s)
    return out


def water_names(text: str) -> list[str]:
    """DC receiving waters named in the text (ECHO's alias table, normalised to the NHD name). Street and
    park names that carry a water's name (Anacostia Avenue, Rock Creek and Potomac Parkway, Rock Creek
    Park, Kenilworth Park & Aquatic Gardens) are not waters."""
    from ingest.echo_sewer_overflow_events import DC_WATER_ALIASES, _alias_key
    t = re.sub(r"\b(?:Rock Creek(?: and Potomac)? (?:Park|Parkway|Pkwy|Trail|Multi-Use Trail)|Anacostia (?:Ave|Avenue|Park|Waterfront)|"
               r"Potomac (?:Ave|Avenue|Street|St|Pkwy)|Potomac Interceptor|Potomac River Tunnel)\b", " ", text, flags=re.I)
    key = _alias_key(t)
    names: dict[str, int] = {}
    for alias, name in DC_WATER_ALIASES.items():
        if alias in ("anacostia", "soapstone", "park rd piney branch pky nw"):
            continue   # a bare word, or a street address typed into a receiving-water field
        m = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", key)
        if m:
            names[name] = min(names.get(name, 10**9), m.start())
    return sorted(names, key=names.get)


def _hhmm(t) -> tuple[int, int]:
    return int(t.group(1)) % 12 + (12 if t.group(3).lower() == "p" else 0), int(t.group(2) or 0)


def started(occ: list[str], near: list[str], published: date, title: str = "") -> tuple[str, str, str, bool, bool, str | None]:
    """(started_at, precision, how, dated, cued, basis) for a discharge the notice reports; basis is the
    sentence that gave the date or the 'today' (None when only the title or the notice date did). `occ` are the sentences
    that report it, `near` those plus the sentence after each (an hour is often there: 'At approximately
    1:40 a.m. ...'). dated: the notice states a date or a weekday for it; cued: it is dated, or the notice
    says 'today' / 'early this morning' / 'overnight', or its title advises the public or investigates
    (a first report). With neither cue the sentence is history, not this notice's discharge."""
    for sent in occ:
        d = DATE_IN_TEXT.search(sent)
        if d:
            month, day = MONTHS[d.group(1).lower()], int(d.group(2))
            year = int(d.group(3)) if d.group(3) else published.year
            try:
                when = date(year, month, day)
            except ValueError:
                continue
            if when > published and not d.group(3):
                when = date(year - 1, month, day)
            t = TIME_IN_TEXT.search(sent)
            if t:
                hh, mm = _hhmm(t)
                return f"{when.isoformat()}T{hh:02d}:{mm:02d}:00", "minute", f"text: {d.group(0)}, {t.group(0)}", True, True, sent
            return when.isoformat(), "day", f"text: {d.group(0)}", True, True, sent
        w = WEEKDAY_IN_TEXT.search(sent)
        if w:   # 'late Monday night' in a Tuesday's notice: the most recent Monday
            wd = WEEKDAYS.index((w.group(1) or w.group(2)).lower())
            when = published - timedelta(days=(published.weekday() - wd) % 7)
            return when.isoformat(), "day", f"text: {_words(w.group(0))}", True, True, sent
    for sent in occ:
        y = YESTERDAY_WORDS.search(sent)
        if y:
            return (published - timedelta(days=1)).isoformat(), "day", f"text: {y.group(0)}", True, True, sent
    today_s = next((x for x in occ if TODAY_WORDS.search(x)), None)
    today = TODAY_WORDS.search(today_s) if today_s else None
    if today:
        for sent in near:
            t = TIME_IN_TEXT.search(sent)
            if t:
                hh, mm = _hhmm(t)
                return f"{published.isoformat()}T{hh:02d}:{mm:02d}:00", "minute", f"text: {_words(t.group(0))}, {today.group(0)}", False, True, today_s
        return published.isoformat(), "day", f"notice date ('{today.group(0)}')", False, True, today_s
    return published.isoformat(), "day", "notice date", False, bool(NOTICE_TITLE.search(title)), None


RATE_TAIL = re.compile(r"^\W*(?:of [\w\s-]{0,30}?\s)?(?:daily|per (?:day|hour|minute)|a day|an hour|each day|every)\b", re.I)


def volume_of(near: list[str]) -> tuple[int | None, str, str | None]:
    """One gallons figure in the discharge sentences (and the sentence after each); never a flow rate
    ('60 million gallons daily') and never one of several figures."""
    figures = []
    for sent in near:
        for m in VOLUME.finditer(sent):
            if not RATE_TAIL.search(sent[m.end():m.end() + 45]):
                figures.append(m)
    if len({m.group(0).lower() for m in figures}) != 1:
        return None, "unknown", None
    m = figures[0]
    gal, flag = parse_volume_gal(f"{m.group(1) or ''}{m.group(2)} {'million ' if m.group(3) else ''}gallons")
    if gal is None:
        return None, flag, None
    return gal, "estimated" if m.group(1) else flag, _words(m.group(0))


def advice_of(text: str) -> str | None:
    for i, s in enumerate(sentences(text)):
        if ADVICE.search(s) and not re.search(r"\bif\b.{0,40}\boccurs?\b", s, re.I):
            return scrub_text(s)
    return None


def classify(item: dict, notice: str | None) -> tuple[dict | None, str]:
    """(facts, reason). facts is None when the notice is not a first report of a discharge."""
    published = parse_item_date(item["date_text"])
    if published is None:
        return None, "date not read"
    body = notice if notice else item["summary"]
    sents = sentences(item["title"] + ". " + body)
    occ = occurrence_sentences(item["title"] + ". " + body)
    text = " ".join([item["title"], item["summary"], body])
    if re.search(r"\b(?:possible|potential|proactive|may occur)\b", item["title"], re.I) and OVERFLOW_WORD.search(item["title"]):
        return None, "precautionary notice of a possible overflow"
    if not occ:
        if re.search(r"possible|potential|may occur|if the overflow", text, re.I) and OVERFLOW_WORD.search(text):
            return None, "precautionary notice of a possible overflow"
        if re.search(r"\bno (?:sewer )?(?:overflows?|spills?)|\bno active (?:spill|overflow)|days (?:with|without) no overflow|"
                     r"no overflow events?|without an? overflow", text, re.I):
            return None, "reports no overflow"
        if any(OVERFLOW_WORD.search(x) and OCCURRENCE.search(x) for x in sents):
            return None, "follow-up on an overflow that started earlier"
        return None, "no overflow reported (repair, closure, testing, meeting or project news)"
    near = []
    for k, x in enumerate(sents):
        if x in occ:
            near += [x, *sents[k + 1:k + 2]]
    when, precision, how, dated, cued, basis = started(occ, near, published, item["title"])
    if not cued:
        return None, "overflow mentioned as history (no date, 'today' or first-report wording)"
    if dated and (published - date.fromisoformat(when[:10])).days > FOLLOWUP_DAYS:
        return None, "follow-up on an overflow that started earlier"
    lede = " ".join(sents[:8])
    waters = water_names(" ".join(occ) + " " + lede)
    cso = any(re.search(r"combined sewer overflow", x, re.I) for x in occ)
    interceptor = bool(re.search(r"potomac interceptor", " ".join(occ) + " " + item["title"], re.I))
    ongoing = any(re.search(r"\b(?:is occurring|is ongoing|continues? to overflow|periodically continues|began coming|coming from|flowing)\b", x, re.I)
                  for x in occ)
    k = sents.index(basis) if basis in sents else None   # the volume of the discharge the date belongs to
    gal, flag, vtext = volume_of([basis, *sents[k + 1:k + 4]] if k is not None else near)
    return {"published": published, "started_at": when, "precision": precision, "how": how, "waters": waters,
            "cso": cso, "interceptor": interceptor, "ongoing": ongoing, "volume": gal, "estimate": flag,
            "volume_text": vtext, "advice": advice_of(body), "sentences": occ[:3]}, "discharge reported"


def make_event(item: dict, facts: dict, notice_fetched: bool, page: int) -> dict:
    slug = slug_of(item["url"])
    etype = "cso" if facts["cso"] else "sso"
    raw = {"title": item["title"], "date_text": item["date_text"], "notice_slug": slug, "list_page": page,
           "notice_fetched": notice_fetched, "discharge_sentences": facts["sentences"],
           "started_at_basis": facts["how"], "waters_named": facts["waters"],
           "timezone_note": "no timezone in the notice; recorded as given (local time)"}
    if facts["interceptor"]:
        raw["state"] = "MD"
        raw["state_basis"] = ("notice is about the Potomac Interceptor, which runs through Maryland and Virginia; its overflows "
                              "are reported in Maryland, operator unchanged (owner-decision default, Washington DC item 3)")
    return event(
        source_id=SOURCE_ID, source_record_id=slug, event_type=etype,
        status="ongoing" if facts["ongoing"] else "unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER_NAME, npdes_permit=PERMIT,
        waterbody_text="; ".join(facts["waters"]) or None, water_match="none",
        started_at=facts["started_at"], time_precision=facts["precision"],
        published_at=facts["published"].isoformat(), material=MATERIAL[etype],
        volume_gal=facts["volume"], volume_text=facts["volume_text"], estimate_flag=facts["estimate"],
        authority=AUTHORITY, advice_text=facts["advice"], source_url=item["url"], raw=raw)


# ---------------------------------------------------------------- the ECHO twin

def echo_rows(path: Path = ECHO_FILE) -> list[dict]:
    d = read_json(path, {}) or {}
    return [r for r in d.get("records", []) if str(r.get("npdes_permit") or "").startswith("DC") and r.get("started_at")]


def _day(ts: str | None) -> date | None:
    try:
        return date.fromisoformat((ts or "")[:10])
    except ValueError:
        return None


def link_duplicates(records: list[dict], rows: list[dict]) -> int:
    """Set duplicate_of on a news event to the ECHO row of the same overflow (module docstring); returns the count."""
    n = 0
    for rec in records:
        rec["duplicate_of"] = None
        d = _day(rec["started_at"])
        if d is None:
            continue
        mine = {w.strip().lower() for w in (rec["waterbody_text"] or "").split(";") if w.strip()}
        cands = []
        for row in rows:
            s, e = _day(row["started_at"]), _day(row.get("ended_at")) or _day(row["started_at"])
            if s is None or not (s - timedelta(days=MATCH_PAD_DAYS) <= d <= e + timedelta(days=MATCH_PAD_DAYS)):
                continue
            theirs = {w.strip().lower() for w in (row.get("waterbody_text") or "").split(";") if w.strip()}
            if mine and theirs and not (mine & theirs):
                continue
            cands.append((0 if mine & theirs else 1, abs((s - d).days), row["event_id"]))
        if cands and (len(cands) == 1 or min(cands)[0] == 0):
            rec["duplicate_of"] = min(cands)[2]
            n += 1
    return n


# ---------------------------------------------------------------- fetch

def fetch_text(url: str, params: dict | None = None) -> bytes:
    last: Exception | None = None
    for i in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {type(last).__name__}: {last}")


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def read_pages(pages: int, src: Path | None, prev_meta: dict) -> tuple[list[tuple[int, dict]], dict, list[str]]:
    """[(page index, item)], the page hashes of this run, errors. From the site, or from saved pages in `src`."""
    items, hashes, errors = [], {}, []
    for n in range(pages):
        try:
            if src:
                f = src / "news" / f"p{n}.html"
                if not f.exists():
                    break
                content = f.read_bytes()
            else:
                content = fetch_text(LIST_URL, {"page": n})
        except RuntimeError as e:
            errors.append(str(e))
            break
        h = digest(content)
        hashes[str(n)] = h
        if not src and (prev_meta.get("page_hashes") or {}).get(str(n)) != h:
            save_raw(SOURCE_ID, content, "html")
        found = parse_list(content.decode("utf-8", "replace"))
        if not found:
            errors.append(f"page {n}: no news items found (the page layout may have changed)")
            break
        items += [(n, it) for it in found]
        if not src:
            time.sleep(PAUSE_S)
    return items, hashes, errors


def read_notice(url: str, src: Path | None, prev_meta: dict, hashes: dict) -> str | None:
    try:
        if src:
            f = src / "notices" / f"{slug_of(url)}.html"
            content = f.read_bytes() if f.exists() else None
        else:
            content = fetch_text(url)
            time.sleep(PAUSE_S)
    except RuntimeError:
        return None
    if content is None:
        return None
    h = digest(content)
    hashes[url] = h
    if not src and (prev_meta.get("notice_hashes") or {}).get(url) != h:
        save_raw(SOURCE_ID, content, "html")
    return parse_notice(content.decode("utf-8", "replace")) or None


def build(items: list[tuple[int, dict]], src: Path | None, prev_meta: dict) -> tuple[list[dict], dict, dict]:
    """(records, notice hashes, {reason: [dates]}) for the kept items."""
    records, nh, why = [], {}, {}
    seen = set()
    for page, it in items:
        if it["url"] in seen or not KEEP.search(f"{it['title']} {it['summary']}"):
            continue
        seen.add(it["url"])
        notice = read_notice(it["url"], src, prev_meta, nh)
        facts, reason = classify(it, notice)
        if facts is None:
            why.setdefault(reason, []).append((parse_item_date(it["date_text"]) or date.min).isoformat())
            continue
        records.append(make_event(it, facts, notice is not None, page))
    return records, nh, why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", type=int, default=PAGES, help="list pages to read (default 3; 26 reaches July 2024)")
    ap.add_argument("--dir", type=Path, help="replay saved pages (news/p<N>.html, notices/<slug>.html) instead of the site")
    a = ap.parse_args(argv)
    src = a.dir if a.dir and a.dir.is_absolute() else (ROOT / a.dir if a.dir else None)
    path = EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = read_json(path, {}) or {}
    prev_meta = prev.get("meta") or {}
    items, page_hashes, errors = read_pages(a.pages, src, prev_meta)
    if errors or not items:
        err = "; ".join(errors) or "no list pages read"
        write_events(SOURCE_ID, [], ok=False, error=err, meta={"registry_ids": ["dc-dcwater-news-notices"]})
        print(f"{SOURCE_ID}: run not ok ({err})", file=sys.stderr)
        return 1
    new, notice_hashes, why = build(items, src, prev_meta)
    merged = {r["event_id"]: r for r in prev.get("records", [])}
    merged.update({r["event_id"]: r for r in new})
    records = sorted(merged.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    dup = link_duplicates(records, echo_rows())
    meta = {"registry_ids": ["dc-dcwater-news-notices"], "list_url": LIST_URL, "pages": a.pages, "items_read": len(items),
            "new_events": len(new), "duplicates_of_echo": dup, "page_hashes": page_hashes,
            "notice_hashes": {**(prev_meta.get("notice_hashes") or {}), **notice_hashes},
            "not_events": {r: sorted(d) for r, d in sorted(why.items())},
            "cadence": "ad hoc; large overflows get a notice the same day or next morning; no RSS"}
    out = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(items)} items, {len(new)} discharge notices this run, {len(records)} records, "
          f"{dup} matched to an ECHO row; not events: " + "; ".join(f"{len(d)} {r}" for r, d in sorted(why.items())) + f" -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
