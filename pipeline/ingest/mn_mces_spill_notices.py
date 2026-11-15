"""Metropolitan Council Environmental Services (Twin Cities): wastewater spill notices
-> data/build/events/mn-mces-spill-notices.json

Source
  https://metrocouncil.org/Wastewater-Water/Services/Interceptor-Services/Spills.aspx (registry: mn-mces-spill-notices),
  the Metropolitan Council's "Wastewater Spills" page. Its "Spill information" list links one page per spill on the
  Council's 637 miles of regional interceptors ("Information on specific wastewater spills will be updated here and
  posted for one year"). Each page opens with the Council's first account (the day it responded, the place, the
  cause, whether a water was reached) and adds dated update headings ("6/1/2026 - Second Notice") with the follow-up:
  repairs, water sampling, the signs posted at affected areas ("Do Not Enter/ Sewage Spill") and their removal. No
  key, no feed, no terms stated; the index and each linked page are read once a run (a few requests, two seconds
  apart). On 2026-11-14 the list held three spills: Excelsior (May 2026), Minneapolis and Golden Valley (July 2026),
  Eagan (November 2026).
  Law: Minn. Stat. 115.061(c) (the owner of a domestic sewer system promptly notifies downstream users and the public
  by the most efficient means and posts signs at impacted public use areas); these pages are the Council's notices.

Record rules (one sso record per spill page; the Council's interceptor spills are sanitary sewer overflows)
  - Key: the page's name and the start day ("Eagan-Wastewater-Spill:2026-11-03"); source_url the page (no query).
  - Three clocks, kept apart (re-review 2026-11-14 P1-2). The response: the day the Council says it responded
    ("responded Friday afternoon, May 29") is reported_at and raw.responded_on, precision day; the year is the index
    label's ("Excelsior, May 2026") when its month matches, else the earliest dated heading's. A part of the day
    ("afternoon") is kept in raw.time_of_day_words and never turned into an hour. The discharge: its start is not
    given, so started_at stays null (raw.start_basis); the colour runs from the response day. Its stop only where the
    text gives one ("contained ... in under an hour" in the first account: the response day; "stop the spill ...
    Thursday evening" in an update: the latest Thursday on or before that update's date, not before the response):
    raw.spill_stopped_on, precision day. Only a completed, affirmative stop counts ("stopped", "contained", "were able
    to stop"); a planned, attempted or negated one ("will stop", "could not stop") is no stop (STOP_DONE, STOP_NOT;
    verification pass 2026-11-15 P1-2). Otherwise unknown; never invented.
  - The signs: when the Council says it placed "Do Not Enter/ Sewage Spill" signs, that is its own advisory
    (advisory_active, red while it stands; advice_text quotes the signs only, review P1-8). Signs first given in an
    update after the response day start the window on that notice's day (raw._advisory_from), never backdated; before
    it the spill's own clock applies (raw._before_advisory: ended at the stop, else unknown; build/status.py;
    verification pass 2026-11-15 P1-2), and a removal done after such signs ends the red at the end of that day. "Will be removed" is a
    removal announced, not one done: the signs stood to the end of that update's day at least (raw._unlisted_since,
    the end of that local day) and after it the end is not confirmed (raw._end_not_confirmed: hatched, then the
    unresolved rules), never a lift at the announcement. "Have been removed" with the spill's stop given: status ended
    at the stop day and advice_window_hours carries the Council's window from the end of the stop day to the end of
    that update's day (red.event; the site's 72-hour caution counts from the stop, review P1-3). "Have been removed"
    with no stop: red to the end of that day, then the end is not confirmed, as above. The removal's own day is never
    given (raw.signs.removal_note, raw.signs.removal_done). Without signs: ended at the stop day, else unknown with
    no end.
  - Water: "Wastewater reached nearby Mud Pond" gives waterbody_text "Mud Pond" (raw.reached_water true). "No waterbodies
    were impacted" is raw.reached_water false with the Council's words (kept, placed on no water). A water named only
    as nearby or tested and found unaffected ("Bassett Creek and Wirth Lake are nearby", "did not impact the water
    quality of Bassett Creek") is listed in raw.nearby_waters and never placed.
  - Place: raw.city (the index label's town), raw.county from CITY_COUNTY (the county the city lies in; Census) so the
    name placement is county-aware (Minnesota has dozens of Mud Ponds); a city not in the table leaves the county null
    and meta.cities_without_county names it. The street location sentence is kept through the house-number scrub.
  - Operator: discharger_id mn-mces (the Metropolitan Council's row); no plant permit is assigned (an interceptor spill
    is not a plant's discharge).
  - A listed page that does not read as a notice (an error page: no response day, no dated update), first seen or
    not, makes no record and keeps its previous one, and it or a page that cannot be read fails the run (ok=False,
    every previous record kept; review P1-4, re-review P1-3).
  - Revisions: each page's text hash; a changed page appends {seen_at, sha256, headings} to raw._revisions. A page that
    leaves the list (one-year retention) keeps its record with raw.gone_from_index_since; one whose signs were still up
    gets raw._unlisted_since and raw._end_not_confirmed (hatched: the lifting was never seen). A page that cannot be
    read keeps its previous record. An index that cannot be read writes ok=False and every previous record stays.
  - Privacy: the pages carry the Council's office contact only. data/raw keeps the index and, per page, its title, its
    dated headings and its text's hash, not the narrative (raw_save_doc); the record's quoted sentences (NARRATIVE_KEYS)
    and advice go through common.strip_personal, scrub_text, the house-number scrub and the strict scrub with names
    (scrubbed(); review P1-6, re-review P1-5).

Run from pipeline/:  python -m ingest.mn_mces_spill_notices [--dir saved_dir]   (index.html and the pages by name)
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

import common
from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest.generic.fieldmap import scrub_strict_names

SOURCE_ID = "mn-mces-spill-notices"
INDEX_URL = "https://metrocouncil.org/Wastewater-Water/Services/Interceptor-Services/Spills.aspx"
AUTHORITY = "Metropolitan Council Environmental Services (wastewater spill notices)"
DISCHARGER_ID = "mn-mces"
DISCHARGER_NAME = "Metropolitan Council"
TZ = "America/Chicago"
# the county each city of a notice lies in (U.S. Census Bureau places; extend when a notice names a new city)
CITY_COUNTY = {"Excelsior": "Hennepin County", "Minneapolis": "Hennepin County", "Golden Valley": "Hennepin County",
               "Eagan": "Dakota County", "Saint Paul": "Ramsey County", "St. Paul": "Ramsey County",
               "Bloomington": "Hennepin County", "Burnsville": "Dakota County", "Shakopee": "Scott County",
               "Stillwater": "Washington County", "Oak Park Heights": "Washington County", "Anoka": "Anoka County",
               "Coon Rapids": "Anoka County", "Chaska": "Carver County", "Hastings": "Dakota County",
               "Rosemount": "Dakota County", "Empire": "Dakota County", "Maple Plain": "Hennepin County",
               "Mound": "Hennepin County", "Minnetonka": "Hennepin County", "Wayzata": "Hennepin County",
               "Roseville": "Ramsey County", "Maplewood": "Ramsey County", "Woodbury": "Washington County",
               "Cottage Grove": "Washington County", "Lakeville": "Dakota County", "Apple Valley": "Dakota County",
               "Savage": "Scott County", "Prior Lake": "Scott County", "Blaine": "Anoka County",
               "Fridley": "Anoka County", "Brooklyn Park": "Hennepin County", "Plymouth": "Hennepin County",
               "Edina": "Hennepin County", "Richfield": "Hennepin County", "St. Louis Park": "Hennepin County",
               "Saint Louis Park": "Hennepin County", "Chanhassen": "Carver County", "Victoria": "Carver County",
               "Lino Lakes": "Anoka County", "White Bear Lake": "Ramsey County", "Mendota Heights": "Dakota County",
               "South St. Paul": "Dakota County", "Inver Grove Heights": "Dakota County"}
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WATER_WORDS = r"(?:Pond|Lake|Creek|River|Bay|Slough|Marsh|Wetland|Channel)"
NAME = rf"(?:St\.\s+|[A-Z][\w'-]*\s+){{0,3}}{WATER_WORDS}"
RESPONDED = re.compile(r"responded\s+(?:(?P<wd>" + "|".join(WEEKDAYS) + r")\s+)?(?P<part>morning|afternoon|evening|night)?"
                       r",?\s*(?P<month>" + "|".join(MONTHS) + r")\s+(?P<day>\d{1,2})", re.I)
DATED = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*[-–—]\s*(.*)$")
REACHED = re.compile(rf"(?:[Ww]astewater|[Ss]pill|[Ss]ewage)\s+reached\s+(?:the\s+)?(?:nearby\s+)?(?P<w>{NAME})")
NO_WATER = re.compile(r"\bno\s+water\s*bod(?:y|ies)\s+(?:were|was)\s+impacted\b[^.]*\.", re.I)
UNAFFECTED = re.compile(rf"did not (?:impact|affect)(?: the water quality of)?\s+(?P<w>{NAME})")
NEARBY = re.compile(rf"(?P<a>{NAME})(?:\s+and\s+(?P<b>{NAME}))?\s+(?:is|are)\s+nearby")
STOP = re.compile(r"[^.]*\b(?:stop(?:ped)?|contained|isolated)\b[^.]*\.", re.I)
# a stop is taken only from a completed, affirmative action ("stopped", "contained", "isolated", "were able to stop"),
# never from a planned, attempted, hoped-for or negated one ("will stop", "could not stop", "was not contained";
# verification pass 2026-11-15 P1-2)
STOP_DONE = re.compile(r"\b(?:stopped|contained|isolated)\b|\b(?:was|were|been)\s+able\s+to\s+stop\b", re.I)
STOP_NOT = re.compile(r"\b(?:not|never|no|unable|cannot|can['’]?t|couldn['’]?t|didn['’]?t|wasn['’]?t|weren['’]?t|"
                      r"haven['’]?t|hasn['’]?t|fail(?:ed|s|ing)?|will|would|shall|should|may|might|plan(?:s|ned|ning)?|"
                      r"expect(?:s|ed|ing)?|attempt(?:s|ed|ing)?|try|tries|tried|trying|working|work|hope(?:s|d)?|"
                      r"aim(?:s|ed|ing)?|intend(?:s|ed)?|once|if|when)\b", re.I)
SAME_DAY = re.compile(r"within hours|in under an hour|under an hour|within an hour|same day", re.I)
SIGNS_UP = re.compile(r"[Ss]igns warning the public\s*[“\"](?P<q>[^”\"]+)[”\"]\s*(?:will be|have been|were)"
                      r"\s+placed")
SIGNS_DOWN = re.compile(r"\b(?:signs?)\b[^.]*\b(?:will be|have been|has been|were)\s+removed|\bwill be removed\b", re.I)
# a removal done (the signs are down by the update's day), not one announced for later ("will be removed next week")
SIGNS_REMOVED = re.compile(r"\bsigns?\b[^.]*\b(?:have been|has been|were|are now)\s+removed\b|\bremoved the\b[^.]*\bsigns?\b",
                           re.I)


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def text_lines(fragment: str) -> list[str]:
    s = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S | re.I)
    s = re.sub(r"<(?:h\d|p|li|br|div|tr)\b[^>]*>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return [re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip()]


def parse_index(page: str) -> list[dict]:
    """[{url, label}] of the 'Spill information' list; ValueError when the list is not on the page."""
    m = re.search(r"Spill information\s*</h2>(.*?)</ul>", page, re.S | re.I)
    if not m:
        raise ValueError("no 'Spill information' list on the index page")
    out = []
    for a in re.finditer(r'<a\s[^>]*href="(?P<h>[^"]+)"[^>]*>(?P<t>.*?)</a>(?P<tail>[^<]*(?:</strong>)?[^<]*)',
                         m.group(1), re.S | re.I):
        url = urljoin(INDEX_URL, html.unescape(a.group("h")))
        parts = urlsplit(url)
        url = f"{parts.scheme}://{parts.netloc}{parts.path}"
        label = " ".join(text_lines(a.group("t") + a.group("tail"))).strip(" ,")
        if "/Spills/" in url and url not in {x["url"] for x in out}:
            out.append({"url": url, "label": re.sub(r"\s*,\s*", ", ", label)})
    return out


def parse_page(page: str) -> dict:
    """The notice's title, its first account (before the first dated heading) and its dated updates."""
    body = page[page.find("<h1"):] if "<h1" in page else page
    lines = text_lines(body)
    end = next((i for i, x in enumerate(lines) if x.lower() == "contact us"), len(lines))
    lines = lines[:end]
    title = lines[0] if lines else ""
    intro, updates, cur = [], [], None
    for x in lines[1:]:
        m = DATED.match(x)
        if m:
            cur = {"date": date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat(),
                   "heading": m.group(4).strip(), "text": []}
            updates.append(cur)
        elif cur is not None:
            cur["text"].append(x)
        else:
            intro.append(x)
    for u in updates:
        u["text"] = " ".join(u["text"])
    return {"title": title, "intro": " ".join(intro), "updates": updates}


def page_reads(parsed: dict) -> bool:
    """A spill page reads as the Council's notice when its first account names the response day or it has a dated
    update; an error or placeholder page does neither."""
    return bool(RESPONDED.search(parsed.get("intro") or "") or parsed.get("updates"))


def scrubbed(o):
    """Every string with emails, phone numbers, staff names, people's names found by their cues ("reported by ...")
    and street house numbers removed (before any save; fieldmap.scrub_strict_names, re-review 2026-11-14 P1-5)."""
    if isinstance(o, dict):
        return {k: scrubbed(v) for k, v in common.strip_personal(o).items()}
    if isinstance(o, list):
        return [scrubbed(v) for v in o]
    if isinstance(o, str):
        return scrub_strict_names(common.strip_house_numbers(common.scrub_text(o)))
    return o


# the record's fields that quote the notice's words: scrubbed before the record is written
# (the revision history's headings and the index label included, carried ones too; verification pass 2026-11-15 P1-5)
NARRATIVE_KEYS = ("title", "location_text", "spill_stopped_words", "_reached_water_words", "_no_water_reason",
                  "updates", "signs", "time_of_day_words", "_revisions", "label", "_window_end_words", "end_basis",
                  "advisory_from_basis")


def scrub_narrative(rec: dict) -> dict:
    """The record with its quoted fields (NARRATIVE_KEYS) and advice scrubbed; applied to every record build() returns,
    a previous record carried unchanged included, so nothing written before a scrub rule existed is written again."""
    raw = rec.get("raw") or {}
    for k in NARRATIVE_KEYS:
        if k in raw:
            raw[k] = scrubbed(raw[k])
    if rec.get("advice_text"):
        rec["advice_text"] = scrubbed(rec["advice_text"])
    return rec


def raw_save_doc(index: str, pages: dict) -> dict:
    """What data/raw keeps of a run: the index's list, and per page only its title, its dated headings and the hash of
    its parsed text (the narrative itself is not kept; the record keeps the scrubbed sentences it uses)."""
    out = {}
    for u, p in pages.items():
        if not p:
            out[u] = None
            continue
        parsed = parse_page(p)
        out[u] = {"title": parsed["title"], "updates": [{"date": x["date"], "heading": x["heading"]}
                                                       for x in parsed["updates"]],
                  "sha256": hashlib.sha256(json.dumps(parsed, sort_keys=True).encode()).hexdigest()}
    return scrubbed({"index": parse_index(index), "pages": out})


def label_city_month(label: str) -> tuple[str | None, int | None, int | None]:
    m = re.match(r"^(?P<c>.+?),\s*(?P<m>[A-Za-z]+)\s+(?P<y>\d{4})$", label or "")
    if not m or m.group("m").lower() not in MONTHS:
        return (label or None), None, None
    return m.group("c"), MONTHS[m.group("m").lower()], int(m.group("y"))


def build_one(item: dict, parsed: dict, fetched: str, previous: dict | None) -> dict:
    city_label, lab_month, lab_year = label_city_month(item.get("label") or "")
    intro, updates = parsed["intro"], parsed["updates"]
    perr = []
    m = RESPONDED.search(intro)
    start = None
    raw: dict = {"label": item.get("label"), "title": parsed["title"], "time_zone": TZ, "page_url": item["url"],
                 "index_url": INDEX_URL}
    if m:
        mo, dy = MONTHS[m.group("month").lower()], int(m.group("day"))
        years = sorted(int(u["date"][:4]) for u in updates if int(u["date"][5:7]) >= mo)
        yr = lab_year if lab_month == mo else (years[0] if years else lab_year)
        if yr:
            start = date(yr, mo, dy)
            raw["responded_on"] = start.isoformat()
            raw["start_basis"] = ("the spill's start is not given: the Council gives only the day it responded "
                                  "(reported_at, raw.responded_on); the spill began on that day or before it")
            if m.group("wd") and WEEKDAYS[start.weekday()] != m.group("wd").lower():
                perr.append(f"the weekday {m.group('wd')} does not fall on {start.isoformat()}")
        else:
            perr.append("no year for the response day (no index label or dated heading)")
        if m.group("part"):
            raw["time_of_day_words"] = m.group("part").lower()
    else:
        perr.append("no 'responded <day>, <month> <day>' sentence in the first account")
    city = city_label
    cities = [c.strip() for c in re.split(r",|\band\b", city or "") if c.strip()]
    counties = {CITY_COUNTY.get(c) for c in cities}
    raw["city"] = city
    raw["county"] = counties.pop() if len(counties) == 1 and None not in counties else None
    if raw["county"]:
        raw["county_basis"] = f"{' and '.join(cities)} lie{'s' if len(cities) == 1 else ''} in {raw['county']} (U.S. Census Bureau)"
    loc = next((s for s in re.split(r"(?<=\.)\s+", intro) if re.search(r"\b(?:occurred|at the intersection|located)\b",
                                                                      s, re.I)), None)
    if loc:
        raw["location_text"] = loc
    alltext = " ".join([intro] + [u["text"] for u in updates])
    # the water
    w = REACHED.search(alltext)
    nw = NO_WATER.search(alltext)
    nearby = []
    for x in NEARBY.finditer(alltext):
        nearby += [y for y in (x.group("a"), x.group("b")) if y]
    nearby += [x.group("w") for x in UNAFFECTED.finditer(alltext)]
    waterbody = None
    if w:
        waterbody = re.sub(r"^(?:nearby|the)\s+", "", w.group("w").strip(), flags=re.I)
        raw["reached_water"] = True
        raw["_reached_water_words"] = w.group(0)
    elif nw:
        raw["reached_water"] = False
        raw["_no_water_reason"] = f"the Council's notice: \"{nw.group(0).strip()}\""
    else:
        raw["reached_water"] = None
    nearby = [n for n in dict.fromkeys(re.sub(r"^(?:nearby|the)\s+", "", n.strip(), flags=re.I) for n in nearby)
              if n != waterbody]
    if nearby:
        raw["nearby_waters"] = nearby
        raw["nearby_waters_note"] = ("named by the Council as nearby or tested and found unaffected; not placed")
    # the spill's own stop
    stopped = None
    if start:
        sections = [(start, intro)] + [(date.fromisoformat(u["date"]), u["text"]) for u in updates]
        for when, text in sections:
            for sm in STOP.finditer(text):
                sent = sm.group(0)
                if not STOP_DONE.search(sent) or STOP_NOT.search(sent):
                    continue            # planned, attempted or negated: no stop (verification pass P1-2)
                wd = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", sent, re.I)
                if wd:      # the weekday named: the latest one on or before the section's own date
                    back = (when.weekday() - WEEKDAYS.index(wd.group(1).lower())) % 7
                    on = when - timedelta(days=back)
                elif SAME_DAY.search(sent) and when == start:
                    on = start
                else:
                    continue
                if start <= on <= when:      # on the response day or a later day up to the section's own date
                    stopped = on
                    raw["spill_stopped_words"] = sent.strip()
                    break
            if stopped:
                break
    if stopped:
        raw["spill_stopped_on"] = stopped.isoformat()
    # the Council's signs: its own advisory
    up = next(((u["date"], x) for u in [{"date": start.isoformat() if start else None, "text": intro}] + updates
               for x in [SIGNS_UP.search(u["text"])] if x), None)
    down = next((u for u in updates if SIGNS_DOWN.search(u["text"])), None)
    status, ended, advice = ("ended" if stopped else "unknown"), (stopped.isoformat() if stopped else None), None
    window_h, window_basis = None, None
    tz = ZoneInfo(TZ)

    def day_end(d: date) -> datetime:
        return datetime.combine(d + timedelta(days=1), datetime.min.time(), tz)
    if up:
        quote = up[1].group("q").strip()
        advice = f"The Council's signs at the affected areas: \"{quote}\" (its notice of {up[0]})."
        raw["signs"] = {"wording": quote, "posted_per_notice_of": up[0]}
        # signs first given in an update after the response day: the Council's window starts on that notice's day,
        # never backdated to the response; before it the spill's own clock applies (raw._before_advisory, read by
        # build/status.py; verification pass 2026-11-15 P1-2)
        late = bool(start) and bool(up[0]) and date.fromisoformat(up[0]) > start
        if late:
            raw["_advisory_from"] = up[0]
            raw["_before_advisory"] = {"status": "ended" if stopped else "unknown",
                                       "ended_at": stopped.isoformat() if stopped else None,
                                       "ended_at_precision": "day" if stopped else None}
            raw["advisory_from_basis"] = (f"the Council's signs are first given in its notice of {up[0]}, after the day "
                                          f"it responded ({start.isoformat()}): its window starts on that notice's day")
        done = next((u for u in updates if SIGNS_REMOVED.search(u["text"])), None)
        if down or done:
            said = done or down
            d = date.fromisoformat(said["date"])
            raw["signs"]["removal_announced_on"] = said["date"]
            raw["signs"]["removal_done"] = bool(done)
            raw["signs"]["removal_note"] = (
                f"the update of {said['date']} says the signs have been removed; the removal's own day is not given, "
                "only that it was by that day" if done else
                f"the update of {said['date']} says the signs will be removed: a removal announced, not one done; "
                "the day they came down is not given")
        if done and stopped and not late:
            # the spill ended on its stop day and the signs were down by the update's day: the Council's window runs
            # from the end of the stop day to the end of that update's day (red.event), the site's caution from the stop
            # elapsed hours between the two local day-ends, both taken to UTC first (a 23- or 25-hour day across a
            # daylight-saving change counts as it ran; verification pass 2026-11-15 P2-6)
            utc = ZoneInfo("UTC")
            window_h = max(0.0, (day_end(date.fromisoformat(done["date"])).astimezone(utc)
                                 - day_end(stopped).astimezone(utc)).total_seconds() / 3600)
            window_basis = (f"the Council's \"{quote}\" signs stood from its notice of {up[0]} until its update of "
                            f"{done['date']} said they had been removed (to the end of that day)")
            raw["ended_at_precision"] = "day"
            raw["end_basis"] = f"the Council's account puts the stop on {stopped.isoformat()}"
        elif down or done:
            # the signs were standing on the update's day; after it their removal (announced, or done with the spill's
            # own stop not given) is not confirmed: red to the end of that day, then "end not confirmed" (hatched),
            # never a lift at the announcement (re-review 2026-11-14 P1-2)
            said = done or down
            status, ended = "advisory_active", None
            raw["_unlisted_since"] = day_end(date.fromisoformat(said["date"])).astimezone(ZoneInfo("UTC")) \
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            if not (done and stopped):
                raw["_end_not_confirmed"] = True
            raw["_window_end_words"] = (f"the Council's update of {said['date']} says its signs "
                                        f"{'have been' if done else 'will be'} removed; the day they came down is "
                                        "not given")
            raw["end_basis"] = (f"the Council's signs stood to the end of {said['date']} at least; their removal day "
                                "is not given" + ("" if stopped else ", nor the spill's own stop")
                                + ("; they were down by then" if done and stopped else "")
                                + (f"; the spill itself stopped on {stopped.isoformat()}" if stopped else ""))
        else:
            status, ended = "advisory_active", None
            raw["end_basis"] = "the Council's signs stand until an update says they are removed"
            if stopped:
                raw["end_basis"] += f"; the spill itself stopped on {stopped.isoformat()}"
    elif stopped:
        raw["ended_at_precision"] = "day"
        raw["end_basis"] = f"the Council's account puts the stop on {stopped.isoformat()}"
    raw["updates"] = [{"date": u["date"], "heading": u["heading"]} for u in updates]
    sha = hashlib.sha256(json.dumps(parsed, sort_keys=True).encode()).hexdigest()
    raw["page_sha256"] = sha
    prev_raw = (previous or {}).get("raw") or {}
    revs = list(prev_raw.get("_revisions") or [])
    if previous and prev_raw.get("page_sha256") and prev_raw.get("page_sha256") != sha:
        revs.append({"seen_at": fetched, "sha256": sha, "headings": [u["heading"] for u in updates]})
    if revs:
        raw["_revisions"] = revs
    raw["_first_seen_at"] = prev_raw.get("_first_seen_at") or fetched
    raw["_last_seen_in_source"] = fetched
    name = urlsplit(item["url"]).path.rsplit("/", 1)[-1].removesuffix(".aspx")
    srid = f"{name}:{start.isoformat()}" if start else name
    newest = max((u["date"] for u in updates), default=None)
    for k in NARRATIVE_KEYS:
        if k in raw:
            raw[k] = scrubbed(raw[k])
    if advice:
        advice = scrubbed(advice)
    return event(
        source_id=SOURCE_ID, source_record_id=srid, event_type="sso", status=status,
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER_NAME, waterbody_text=waterbody,
        started_at=None, reported_at=start.isoformat() if start else None, ended_at=ended, time_precision="day",
        source_updated_at=newest, fetched_at=fetched, material="untreated sewage", authority=AUTHORITY,
        advice_text=advice, advice_window_hours=window_h, advice_window_basis=window_basis, source_url=item["url"],
        raw=raw, parse_error="; ".join(perr) or None)


def build(index_page: str, pages: dict[str, str | None], fetched: str, previous: list[dict]) -> tuple[list[dict], dict]:
    """(records, meta). pages: url -> html (None when the page could not be read: its previous record stays)."""
    items = parse_index(index_page)
    prev_by_url = {(p.get("raw") or {}).get("page_url"): p for p in previous}
    out: dict[str, dict] = {}
    unread, no_county = [], []
    for it in items:
        page = pages.get(it["url"])
        if page is None:
            if it["url"] in prev_by_url:
                p = prev_by_url[it["url"]]
                out[p["event_id"]] = p
            unread.append(it["url"])
            continue
        parsed = parse_page(page)
        if not page_reads(parsed):
            # a page that is not the notice (an error page), first seen or not: never a record of its own; the
            # previous record stays and the run fails (re-review 2026-11-14 P1-3)
            if it["url"] in prev_by_url:
                p = prev_by_url[it["url"]]
                out[p["event_id"]] = p
            unread.append(it["url"])
            continue
        rec = build_one(it, parsed, fetched, prev_by_url.get(it["url"]))
        if not rec["raw"].get("county"):
            no_county.append(rec["raw"].get("city"))
        out[rec["event_id"]] = rec
    listed = {it["url"] for it in items}
    kept = 0
    for p in previous:
        if p["event_id"] in out or (p.get("raw") or {}).get("page_url") in listed:
            continue
        p = json.loads(json.dumps(p))
        raw = p["raw"]
        raw["gone_from_index_since"] = raw.get("gone_from_index_since") or fetched
        if p.get("status") == "advisory_active":
            raw["_unlisted_since"] = raw.get("_unlisted_since") or fetched
            raw["_end_not_confirmed"] = True
        out[p["event_id"]] = p
        kept += 1
    recs = sorted((scrub_narrative(json.loads(json.dumps(r))) for r in out.values()), key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]),
                  reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": INDEX_URL, "on_index": len(items), "pages_unread": unread,
            "kept_from_previous": kept, "cities_without_county": sorted({c for c in no_county if c}),
            "advisory_active": sum(1 for r in recs if r["status"] == "advisory_active"),
            "cadence": "index and each listed page read every run; the Council posts and updates a page per spill",
            "credit": "Metropolitan Council Environmental Services",
            "caveat": ("The Council's own notices of spills from its regional interceptors, posted for one year. City "
                       "sewers and other operators are not covered; a spill the Council has not yet written up has "
                       "no page.")}
    return recs, meta


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=(20, 120))
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    try:
        if "--dir" in argv:
            d = Path(argv[argv.index("--dir") + 1])
            index = (d / "index.html").read_text(errors="replace")
            pages = {}
            for it in parse_index(index):
                f = d / (urlsplit(it["url"]).path.rsplit("/", 1)[-1])
                pages[it["url"]] = f.read_text(errors="replace") if f.exists() else None
        else:
            index = fetch(INDEX_URL)
            pages = {}
            for it in parse_index(index):
                time.sleep(2)
                try:
                    pages[it["url"]] = fetch(it["url"])
                except requests.RequestException:
                    pages[it["url"]] = None
            save_raw(SOURCE_ID, json.dumps(raw_save_doc(index, pages), indent=1), "json")
        recs, meta = build(index, pages, fetched, prev)
        if meta["pages_unread"]:
            raise RuntimeError(f"spill pages not read: {', '.join(meta['pages_unread'])}")
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['on_index']} on the index, {len(recs)} records, {meta['advisory_active']} signs standing"
          f" -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
