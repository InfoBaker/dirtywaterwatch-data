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
  channels if at all: the post itself comes with the letter, one to six days after the overflow where the post dates it).
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
    come from a combined sewer outfall) with the basis stated, never left unknown. A clause that names both types
    ("A combined sewer overflow and a separate sewer overflow occurred on June 1") gives both records, each with the
    words that belong to it (type_spans): its own date where each has one, the shared one where they share it, its own
    water, and a denial only for the type it denies ("... and no separate sewer overflow"); each type's own figure
    ("A combined sewer overflow of 100 gallons and a separate sewer overflow occurred"), stated minutes and end, and
    water are read from its own words and the shared predicate, never lost to the other type's figure or denial.
    "Combined and separate sewer overflows" names both; a denial joined by "or" or "nor" denies both; "Both overflows
    ended at ..." gives the end to every type the post reports.
  - Times, America/Chicago (Milwaukee; raw.time_zone): the post's own stamp ("08/06/26 09:00:am") is published_at.
    reported_at stays null (the post gives the letter's subject, not its receipt date). started_at: a stated start
    ("started at 5:55 pm on April 2, 2024"; "around 10:00 a.m. on 9-3-26"), precision minute, when the nearest cue before
    the time is a start and not an end ("ended at 2:00 pm on June 2" is never a start); else the day a sentence about
    that overflow ties to its occurrence ("A combined sewer overflow occurred on June 1, 2027"; "the wastewater spill on
    September 18"), precision day (occurrence_day). A date after an end, a report or a storm word is not a start: "ended
    at 2:00 pm on June 2" stays the end, "was reported on June 2" is kept as raw.reported_day (never reported_at, never
    a start), and where no start is tied raw.start_basis says the post gives none. A start verb is the overflow's
    only when the overflow is its subject or object: "Heavy rain began on June 1 and led to a combined sewer
    overflow", "Repairs began at 8:00 am on June 3" and "crews started cleanup" give no start, and a repair's or a
    cleanup's day is not the storm's period either (_overflow_subject). The dates the title or
    the opening sentence give for the storm ("August 1st, 2026", "Aug 9-10, 2025", "8-20-18") are not the overflow's
    start: they are kept as raw.period_start / raw.period_end and raw.started_after (a lower bound), started_at stays
    null and the status engine counts from the post's publication (Astra re-review 2026-11-15 P1-2). A date with no
    year takes the post's year, or the year before when that would put it after the post. ended_at only from a stated, completed end ("ended at 8:10 pm on
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

Privacy: only the candidate posts' list items (titles scrubbed) and each one's stamp, letter links and the article's
evidence sentences (project(): a type, a volume, a date, a water; nothing else, no signature) are kept; people named
in the text ("Director Pat Example", "said ...", "Pat Example reported", any run of capitalised words holding none of
the source's own words: KNOWN) are cut (scrub_names), "the home of ..." becomes "a private residence", a link label
that is not about the letter becomes "letter"; in a run of capitalised words, two or more of none of the source's own
words, or one next to a known word that is also a name ("May Example"), are cut while the rest stays ("[name removed]
Reports Sewer Overflow"), and a place's name before a place word ("Indian Creek") is kept; every point in a post (or a
record) that describes a private home anywhere is removed entirely, whichever paragraph it is in, and any other point
is rounded to three decimals figure by figure (a pair at any precision, a lone "43.1234 N", degrees-minutes-seconds cut
to the minute); records carried from an earlier run are scrubbed again on every write (rescrub); the article is cut at MMSD's standing advice block ("Text WATERDROP ...") or at a contact line ("Questions:",
"Media contact"), so the people named there are never kept, and telephone numbers and e-mails are scrubbed (common.scrub_text), house numbers
removed (common.strip_house_numbers). data/raw keeps that safe document only.

Failures: a list page that cannot be read writes ok=False and keeps the previous records; a post that cannot be read is
read again next run, its earlier records kept as they were, while the posts read well in the same run are written at
once (ok=False, last_ok_at unchanged: common.write_events partial=True).

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
# an end only from words saying the overflow did end ("ended at", "continued until"): "will continue until" and the
# like are not ends (Astra re-review 2026-11-15 P1-3); NEGATED also refuses the clause
END_RX = [
    re.compile(rf"\b(?:continued|lasted|ran|persisted)\s+until\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\bended\s+at\s+{CLOCK}\s+on\s+(?P<d>{ANY_DATE})", re.I),
    re.compile(rf"\bended\s+on\s+(?P<d>{ANY_DATE}),?\s+at\s+{CLOCK}", re.I),
]

# the last cue before a time says whose time it is: "ended at 2:00 pm on June 2" is never a start (Astra re-review
# 2026-11-15 P1-2)
START_CUE = re.compile(r"\b(?:began|begin\w*|start\w*|occurred|occured|took place|triggered|initiated)\b", re.I)
END_CUE = re.compile(r"\b(?:ended|ending|end|until|stopped|ceased|concluded|lasted|continued)\b", re.I)


# a start verb is the overflow's only when the overflow is its subject ("A combined sewer overflow began on June 1") or
# its object ("MMSD initiated a combined sewer overflow"): rain, a storm, repairs, a cleanup or crews that began or
# started something give no start (Astra verification 3, 2026-11-15, #2)
OVERFLOW_NOUN = re.compile(r"\b(?:overflow|spill|release|discharge|bypass)\w*|\bcsos?\b|\bssos?\b", re.I)
OTHER_SUBJECT = re.compile(r"\b(?:rain\w*|storm\w*|thunderstorm\w*|precipitation|snow\w*|flood\w*|weather|"
                           r"repair\w*|clean-?up\w*|cleaning|work|crews?|construction|maintenance|inspection\w*|"
                           r"investigation\w*|response|pumping|sampling|testing|monitoring|outage|power)\b", re.I)
CLEANUP = re.compile(r"\b(?:repair\w*|clean-?up\w*|cleaning|crews?|construction|maintenance|inspection\w*|"
                     r"investigation\w*|pumping|sampling|testing|monitoring)\b", re.I)
OBJECT = re.compile(r"\s+(?:(?:an?|the|its|their)\s+)?(?:[\w-]+\s+){0,3}?(?:overflow|spill|release|discharge|bypass)\w*"
                    r"|\s+(?:(?:an?|the)\s+)?(?:csos?|ssos?)\b", re.I)


def _overflow_subject(text: str, cue: re.Match) -> bool:
    """True when the start verb cue speaks of the overflow: the last overflow word before it with no other subject
    between, or an overflow as its object."""
    pre = text[:cue.start()]
    last = None
    for last in OVERFLOW_NOUN.finditer(pre):
        pass
    if last is not None and not OTHER_SUBJECT.search(pre[last.end():]):
        return True
    obj = OBJECT.match(text, cue.end())
    return bool(obj and not OTHER_SUBJECT.search(obj.group(0)))


def _start_owned(text: str, m: re.Match) -> bool:
    """True when the nearest cue before the time m is a start cue, not an end cue, and the overflow is what started."""
    pre = text[:m.start()] + text[m.start():m.end()].split(m.group("h"), 1)[0]
    s = list(START_CUE.finditer(pre))
    e = [x.end() for x in END_CUE.finditer(pre)]
    return bool(s) and (not e or s[-1].end() > max(e)) and _overflow_subject(text, s[-1])


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
# a sentence about the overflows together ("Both overflows ended at 2:00 pm on June 2") speaks for every type the post
# reports (verification 3, #1)
BOTH = re.compile(r"\bboth\b[^.;]{0,40}\boverflows\b|\b(?:the|these|those)\s+(?:two\s+)?overflows\b|"
                  r"\beach overflow\b", re.I)
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
# people named in a post's own words (Astra re-review 2026-11-15 P1-6): a name after a role or title ("Director Pat
# Example", "Mr. Example"), after or before a speech verb ("said Pat Example", "Pat Example said"), or before a role
# ("Pat Example, district engineer"); each becomes [name removed]. Names are capitalised words; roles any case.
ROLE = (r"(?:executive\s+director|deputy\s+director|director|manager|engineer|spokes(?:person|man|woman)|commissioner|"
        r"chief|superintendent|mayor|alder(?:man|woman|person)?|supervisor|president|chair(?:man|woman|person)?|ceo|"
        r"officer|coordinator|specialist|dr|mr|mrs|ms|mx)\.?")
PNAME = r"(?:[A-Z][a-z'’-]+|[A-Z]\.)(?:\s+(?:[A-Z][a-z'’-]+|[A-Z]\.)){0,3}"
NAME_RX = [
    (re.compile(rf"\b(?i:{ROLE})\s+(?P<n>{PNAME})"), "[name removed]"),
    (re.compile(rf"\b(?P<v>said|says|according to|stated by|quoted)\s+(?P<n>{PNAME})"), r"\g<v> [name removed]"),
    # a name before a speech or report verb ("Pat Example reported ..."; Astra verification 2026-11-15, earlier #6)
    (re.compile(rf"\b(?P<n>{PNAME})\s+(?=(?:said|says|stated|explained|noted|added|told|reported|reports|confirmed|"
                rf"announced|wrote|observed|noticed|called|saw|found|discovered)\b)"), "[name removed] "),
    (re.compile(rf"\b(?P<n>{PNAME}),\s+(?=(?:an?\s+|the\s+|MMSD'?s?\s+)?(?:[\w-]+\s+){{0,3}}(?i:{ROLE})\b)"),
     "[name removed], "),
]
# the capitalised words MMSD's posts use for itself, its plants, the waters, the places and the overflow types: a run of
# capitalised words is a person's name unless it holds one of these (Astra verification 2026-11-15, earlier #6). A name
# before a verb is kept only when every word is one of these ("The Milwaukee Metropolitan Sewerage District reported")
KNOWN = set("""
a an the this that these those there their it its in on at of for from to into by with and or but after before during
between through until since while when where as no not any all one two three four five six seven eight nine ten
mmsd dnr epa wi wisconsin milwaukee metropolitan sewerage district department natural resources state city county
village town north south east west northern southern eastern western upper lower greater regional public
combined separate sanitary sewer sewers sewage overflow overflows overflowed release releases spill spills wastewater
water waters stormwater storm storms update updates alert alerts letter letters notice report reports reporting
reported dnr's mmsd's treatment plant plants reclamation facility facilities deep tunnel tunnels system systems
lake michigan creek creeks river rivers harbor harbour canal estuary inner outer bay beach beaches park
kinnickinnic menomonee milwaukee root lincoln wilson honey underwood oak jones island south shore little
wauwatosa west allis greenfield glendale shorewood whitefish fox point bayside hills brown deer cudahy st francis
franklin greendale hales corners mequon thiensville brookfield elm grove butler falls germantown new berlin
caledonia muskego superior veolia accidental heavy rain rainfall flooding flood volume volumes estimated
gallons million billion steps taken prevent other discharges discharge impacted impact map view see more
information update read about overview background summary next what why how who our we you
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday
cso csos sso ssos street avenue road drive boulevard parkway highway st ave rd dr blvd n s e w
mitchell international airport national weather service gauge gauges
day days notification notifications help manage managing can could will do does take takes taken future steps
total totals winter spring summer fall falls autumn heavy rains dangerous safety safe stay keep avoid contact
basin management reach watershed grounds valley project projects flood floods program programs plan plans
news press media statement statements frequently asked questions faq new latest week weekend today tonight
""".split())
RUN = re.compile(r"\b(?:[A-Z][a-z'’-]+|[A-Z]\.)(?:\s+(?:[A-Z][a-z'’-]+|[A-Z]\.))+")


def _known(w: str) -> bool:
    return re.sub(r"(?:'s|’s|[.,'’-])+$", "", w).lower() in KNOWN


def _name_sub(rep: str):
    def f(m: re.Match) -> str:
        if all(_known(w) for w in m.group("n").split()):
            return m.group(0)               # the district, a plant, a water or a place, not a person
        return m.expand(rep)
    return f


# a point described as a private home is removed entirely, not rounded (Astra verification 2026-11-15, earlier #6);
# other points in the text are cut to three decimals, as every report point is
COORD = re.compile(r"(-?\d{1,3}\.\d{4,})(\s*,\s*)(-?\d{1,3}\.\d{4,})")
ANY_COORD = re.compile(r"(?:\(\s*)?-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+(?:\s*\))?")
PRIVATE_PLACE = re.compile(r"\b(?:home|homes|house|houses|residen\w*|dwelling|apartment|condo\w*|basement|backyard|"
                           r"yard|driveway|private property|property owner)\b", re.I)
HOME_OF = re.compile(rf"\b(?:the\s+)?(?:home|house|residence|property|yard|basement|apartment)\s+of\s+"
                     rf"(?:\[name removed\]|{PNAME})")


# an unknown word right before one of these is a place's name ("Indian Creek", "Example Avenue"), not a person's
PLACE_SUFFIX = set("""
creek creeks river rivers harbor harbour canal lake park street avenue road drive boulevard parkway highway lane court
way place st ave rd dr blvd ln ct plant facility island county village city town valley bay beach pond ditch branch
tributary airport station school center centre
""".split())
# known words that are also given names or surnames: next to an unknown word in a run they are part of the name ("May
# Example", "Pat Jones"), and go with it (Astra verification 3, 2026-11-15, #6)
NAMEISH = set("""
may june april august lincoln wilson jones mitchell franklin brown butler fox root oak honey hales st grove park
""".split())


def _run_sub(m: re.Match) -> str:
    """A run of capitalised words: two or more unknown words together, or one next to a name-like known word, are a
    name and are cut with that word, unless they are a place's name before a place word; a run of known words only is
    kept, and so is one unknown word among known ones ("Heavy Rains", "5-Day Letter")."""
    ws = m.group(0).split()
    unk = [not _known(w) for w in ws]
    if not any(unk):
        return m.group(0)
    if all(unk):
        return "[name removed]"
    nameish = [re.sub(r"(?:'s|’s|[.,'’-])+$", "", w).lower() in NAMEISH for w in ws]
    cut = [u and ((i > 0 and (unk[i - 1] or nameish[i - 1])) or (i + 1 < len(ws) and (unk[i + 1] or nameish[i + 1])))
           for i, u in enumerate(unk)]
    i = 0
    while i < len(ws):
        if cut[i]:
            j = i
            while j < len(ws) and cut[j]:
                j += 1
            if j < len(ws) and re.sub(r"[.,'’-]+$", "", ws[j]).lower() in PLACE_SUFFIX:
                for k in range(i, j):
                    cut[k] = False      # "Indian Creek": a place
            i = j
        else:
            i += 1
    for i in [i for i, c in enumerate(cut) if c]:
        for k in (i - 1, i + 1):
            if 0 <= k < len(ws) and not cut[k] and re.sub(r"(?:'s|’s|[.,'’-])+$", "", ws[k]).lower() in NAMEISH:
                cut[k] = True
    out, i = [], 0
    while i < len(ws):
        if cut[i]:
            while i < len(ws) and cut[i]:
                i += 1
            out.append("[name removed]")
        else:
            out.append(ws[i])
            i += 1
    return " ".join(out)


def scrub_names(s: str) -> str:
    s = HOME_OF.sub("a private residence", s)
    for rx, rep in NAME_RX:
        s = rx.sub(_name_sub(rep), s)
    # in any other run of capitalised words, the words that are none of the source's own are a name; the known words
    # around them stay ("[name removed] Reports Sewer Overflow"; Astra verification 3, #6)
    return RUN.sub(_run_sub, s)


# every form of a point in free text (Astra verification 3, #6): a pair at any precision, a lone degree figure with
# four or more decimals ("43.1234 N", "latitude 43.223456"), and degrees, minutes and seconds
FINE = re.compile(r"(?<![\d.])(-?\d{1,3})\.(\d{4,})(?!\d)(?!\.\d)")
DMS = re.compile(r"(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*\d{1,2}(?:\.\d+)?\s*(?:\"|″|'')?")
PRIVATE_POINT = re.compile(r"(?:\(\s*)?-?\d{1,3}\.\d+\s*°?\s*[NSEW]?\s*,?\s*-?\d{1,3}\.\d+\s*°?\s*[NSEW]?(?:\s*\))?|"
                           r"-?\d{1,3}\.\d{3,}\s*°?\s*[NSEW]?|\d{1,3}\s*°\s*\d{1,2}\s*['′](?:\s*\d{1,2}(?:\.\d+)?\s*"
                           r"(?:\"|″|'')?)?\s*[NSEW]?|-?\d{1,3}\.\d+\s*°?\s*[NSEW]\b")


def safe_line(s: str, private: bool | None = None) -> str:
    """Phones and e-mails scrubbed, house numbers removed, people's names cut; every point in a text that describes a
    private home (private: the line itself, or the post or record it belongs to) removed, any other rounded to three
    decimals, each figure on its own; a month's day ("June 18 at 35th St.") is not a house number."""
    glued = DATE_GLUE.sub(lambda m: m.group(1) + "\u2060_", s)
    s = strip_house_numbers(scrub_text(glued)).replace("\u2060_", " ")
    if private or (private is None and PRIVATE_PLACE.search(s)):
        s = PRIVATE_POINT.sub("[location removed]", s)
    s = DMS.sub(lambda m: f"{m.group(1)}°{m.group(2)}'", s)
    s = FINE.sub(lambda m: f"{round(float(m.group(1) + '.' + m.group(2)), 3)}", s)
    return scrub_names(s)


# the minimal factual projection kept of an article (Astra re-review 2026-11-15 P1-6): only the sentences that can carry
# a report (a type, an overflow, spill or release, a volume, a date or time, a water reached or not); signatures,
# quotes about other things, and other prose are not kept, in raw storage or anywhere else
EVIDENCE = re.compile(rf"overflow|spill|releas|discharg|bypass|wastewater|sewage|gallons|\bcsos?\b|\bssos?\b|"
                      rf"\b{MON}\s+\d|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2}}|\b\d{{1,2}}(?::\d\d)?\s*[ap]\.?\s*m\b|"
                      rf"creek|river|lake|harbor|canal", re.I)
LABEL_OK = re.compile(r"overflow|spill|releas|letter|report|\bdnr\b|notice|\bcsos?\b|\bssos?\b", re.I)


def project(line: str) -> str:
    """The sentences of a line that carry evidence, joined; '' when none does."""
    t = re.sub(r"\b([ap])\.m\.", r"\1m", line)
    t = re.sub(r"\b(St|Ave|No|Dr|Mt|U\.S)\.", r"\1", t)
    keep = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"“])", t) if EVIDENCE.search(x)]
    return " ".join(keep)


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
    letters, lines, blocks = [], [], []
    for block in re.split(r"<(?:/?(?:p|div|li|ul|ol|h\d|tr|table|br|hr)\b)[^>]*>", body, flags=re.I):
        w = _words(re.sub(r"<[^>]+>", " ", block))
        if not w:
            continue
        if CUT.search(w) or CONTACT.search(w):
            break                       # MMSD's standing advice block, or a contact block naming people
        blocks.append((block, w))
    # a post that describes a private home anywhere has every point in it removed: the home in one paragraph and its
    # point in the next are one place (Astra verification 3, #6)
    private = any(PRIVATE_PLACE.search(w) for _, w in blocks)
    for block, w in blocks:
        for m in re.finditer(r'<a\s[^>]*href="([^"]*download_file[^"]*)"[^>]*>(.*?)</a>', block, re.S | re.I):
            label = safe_line(_words(re.sub(r"<[^>]+>", " ", m.group(2))), private)
            label = label if LABEL_OK.search(label or "") else "letter"     # a label that is not about the letter
            if label and {"url": m.group(1), "label": label} not in letters:
                letters.append({"url": m.group(1), "label": label})
        lines.append(safe_line(w, private))
    stamp = next((x for x in lines[:4] if STAMP.match(x)), None)
    rest = [x for x in lines if x != stamp]
    # the title line (the page title block, first) is kept as it is (scrubbed); the article below it is projected
    body = rest[:1] + [y for y in (project(x) for x in rest[1:]) if y]
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


def _date_hits(text: str, ref: date) -> list[tuple[int, date, date | None, str]]:
    """(position, first day, last day or None, the words) of every date or range in text, in order."""
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
    return [(i, a, (b if b is None or b >= a else None), w.strip()) for i, a, b, w in sorted(hits, key=lambda h: h[0])]


def period(text: str, ref: date, skip_tied: bool = False) -> tuple[date, date | None, str] | None:
    """(first day, last day or None, the words) of the first date or range in text; with skip_tied, a date the text
    ties to an end or to a report ("ended ... on June 2", "was reported on June 2") is passed over."""
    for i, first, last, words in _date_hits(text, ref):
        if skip_tied:
            cues = [(m.end(), k) for k, rx in (("s", START_TIE), ("e", END_CUE), ("r", REPORT_TIE))
                    for m in rx.finditer(text[:i])]
            if cues and max(cues)[1] in "er":
                continue
            if CLEANUP.search(re.split(r"[.;]", text[:i])[-1]):
                continue                # a repair's or a cleanup's day is not the storm's (verification 3, #2)
        return first, last, words
    return None


# a date is the overflow's start only where the text ties it to the occurrence or the start: after "occurred",
# "took place", "began", "started", "initiated" or "triggered", or right after the overflow itself ("the wastewater
# spill on September 18"), with no end, report or storm word between; an end stays an end and a reporting day stays a
# reporting day (Astra verification 2026-11-15, earlier #2)
START_TIE = re.compile(r"\b(?:began|begin\w*|start\w*|occurred|occured|occurring|took place|triggered|initiated)\b",
                       re.I)
NOUN_ON = re.compile(r"\b(?:overflow|spill|release|discharge|bypass)\w*\s+on\s+$", re.I)
REPORT_TIE = re.compile(r"\b(?:report\w*|posted|published|submitted|sent|notified|announced|filed|letter)\b", re.I)
NOT_START = re.compile(r"\b(?:ended|ending|end|until|stopped|ceased|concluded|lasted|continued|report\w*|posted|"
                       r"published|submitted|sent|notified|announced|filed|letter|rain\w*|storm\w*)\b", re.I)
# the day the overflow was reported ("was reported on June 2"; "reported a combined sewer overflow to the DNR on June
# 2"): kept as raw.reported_day, never a start; reported_at stays null (the receipt date is not given)
REPORTED_ON = re.compile(rf"\breport(?:ed|s)\b(?:(?!occurr|occur|took place|began|start)[^.;]){{0,120}}?\bon\s+"
                         rf"(?P<d>{ANY_DATE})", re.I)


def occurrence_day(text: str, ref: date) -> tuple[date, str] | None:
    """(day, words) of the first date text ties to the overflow's occurrence or start; None when none is tied."""
    for i, first, _, words in _date_hits(text, ref):
        pre = text[:i]
        verbs = list(START_TIE.finditer(pre))
        if verbs and not _overflow_subject(text, verbs[-1]) and not NOUN_ON.search(pre):
            continue                    # rain, a storm, repairs or a cleanup began: not the overflow (verification 3)
        anchors = [m.end() for m in verbs] + ([len(pre)] if NOUN_ON.search(pre) else [])
        if anchors and not NOT_START.search(pre[max(anchors):]):
            return first, words
    return None


# two types named together ("Combined and separate sewer overflows occurred"; "separate and combined sewer
# overflows"; "combined sewer and sanitary sewer overflows") are read as two mentions, each its own type (Astra
# verification 3, 2026-11-15, #1)
TWO_TYPES = re.compile(r"\b(?P<a>combined|separate|sanitary)(?:\s+sewer)?\s+(?P<j>and|&|or|nor)\s+"
                       r"(?P<b>combined|separate|sanitary)\s+sewer\s+(?P<o>overflows?)\b", re.I)


def expand_types(s: str) -> str:
    return TWO_TYPES.sub(lambda m: f"{m.group('a')} sewer {m.group('o')} {m.group('j')} {m.group('b')} sewer "
                                   f"{m.group('o')}", s)


# where a borrowed predicate begins: the verb, a denial or a labelled figure, never the lender's own water, volume or
# article ("A combined sewer overflow and a separate sewer overflow into Honey Creek occurred": "occurred ...")
PRED = re.compile(REPORT_CUE.pattern + "|" + NEGATED.pattern + "|" + NOT_REPORT.pattern
                  + r"|\b(?:did|was|were|has|have|had|is|are)\b", re.I)


def type_spans(s: str) -> list[tuple[str, str, str]]:
    """[(type, its own words, its own mention's words only)] of a sentence naming more than one type: each mention
    with the words up to the next one; a mention with no verb of its own ("A combined sewer overflow and a separate
    sewer overflow occurred on June 1") shares the predicate of the next mention that has one, from that mention's
    verb on: never that mention's own article, denial, water or volume ("A combined sewer overflow and no separate
    sewer overflow occurred": the denial is the second's only; Astra verification 2026-11-15, earlier #1; verification
    3, #1). A denial joined by "or" or "nor" ("No combined sewer overflow or separate sewer overflow occurred";
    "Neither ... nor ...") denies every type it joins."""
    ms = sorted((m.start(), m.end(), t) for t, rx in TYPE_WORDS.items() for m in rx.finditer(s))
    men: list[list] = []
    for a, b, t in ms:
        if men and a < men[-1][1]:
            continue                            # overlapping mention
        if men and men[-1][2] == t and not s[men[-1][1]:a].strip(" ()"):
            men[-1][1] = b                      # "combined sewer overflow (CSO)"
            continue
        men.append([a, b, t])
    if len(men) < 2:
        return []
    starts = []
    for k, (a, _, _) in enumerate(men):
        if k == 0:
            starts.append(0)
            continue
        q = re.search(r"\b(?:no|an?|the|any|both)\s+(?:[a-z]+\s+)?$", s[:a], re.I)
        starts.append(q.start() if q and q.start() >= men[k - 1][1] else a)
    ends = [starts[k + 1] if k + 1 < len(men) else len(s) for k in range(len(men))]
    segs = [s[starts[k]:ends[k]] for k in range(len(men))]
    # a denial joined by "or" / "nor" carries to the next type
    for k in range(1, len(men)):
        joint = s[men[k - 1][1]:starts[k]]
        if re.search(r"\b(?:or|nor)\b", joint, re.I) and NEGATED.search(s[starts[k - 1]:men[k - 1][1]]) \
                and not NEGATED.search(segs[k]):
            segs[k] = "no " + segs[k]

    def has_verb(k: int) -> bool:
        return bool(REPORT_CUE.search(segs[k]) or NEGATED.search(segs[k]) or NOT_REPORT.search(segs[k]))
    out = []
    for k, (_, _, t) in enumerate(men):
        own = segs[k]
        if not has_verb(k):
            j = next((j for j in range(k + 1, len(men)) if has_verb(j)), None)
            if j is not None:
                tail = s[men[j][1]:ends[j]]
                v = PRED.search(tail)
                own = own.rstrip() + " " + (tail[v.start():] if v else tail).lstrip()
        out.append((t, own, segs[k]))
    return out


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
    out, last = [], 0
    for m in CLAUSE.finditer(sentence):
        left = sentence[last:m.start()]
        if not REPORT_CUE.search(left) and not NEGATED.search(left) and any(r.search(left) for r in TYPE_WORDS.values()):
            continue                    # "A combined sewer overflow and no separate sewer overflow occurred": the
            # first has no verb of its own and shares the sentence's (Astra verification 2026-11-15, earlier #1)
        out.append(left)
        last = m.end()
    out.append(sentence[last:])
    return [c.strip() for c in out if c and c.strip()]


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
    quote: dict[str, str] = {}                              # a clause read with its types expanded -> MMSD's words
    sents = []
    for x in sentences(body):
        ex = expand_types(x)
        for c in clauses(ex):
            sents.append(c)
            if ex != x:
                quote[c] = x
    lede = " ".join(sents[:3])
    per = period(title, ref) or period(lede, ref, skip_tied=True)
    facts = {"published": pub, "period": per, "types": {}, "local": [], "no_water": None}
    types: dict[str, dict] = {}

    def affirmative(x: str) -> bool:
        """A sentence that reports an overflow: a report cue, no denial, hedge, plan or prevention."""
        return (bool(REPORT_CUE.search(x)) and not NEGATED.search(x) and not LOCAL.search(x)
                and not any(_gal(z) == 0 for z in LABELLED.finditer(x)))

    def _times(x: dict, text: str) -> None:
        """The stated start, end and reporting day in text, for the one overflow x the text is about."""
        if x.get("reported") is None:
            rm = REPORTED_ON.search(text)
            d = parse_date(rm.group("d"), ref) if rm else None
            if d:
                x["reported"] = (d, _words(rm.group("d")))
        for key, rxs in (("start", START_RX), ("end", END_RX)):
            if x[key]:
                continue
            for rx in rxs:
                m = rx.search(text)
                if m and key == "start" and not _start_owned(text, m):
                    m = None
                d = parse_date(m.group("d"), ref) if m else None
                if d:
                    x[key] = (_at(d, m), m.group(0))
                    break

    def add(t: str, basis: str) -> dict:
        x = types.setdefault(t, {"basis": basis, "volume": None, "volume_text": None, "covers": None, "waters": [],
                                 "start": None, "end": None, "day": None, "reported": None})
        return x

    for s in sents:
        if LOCAL.search(s):
            facts["local"].append(s)
    def units(x: str) -> list[tuple[str | None, str, str]]:
        """[(type, its own words, its own mention's words)]: one per type a multi-type sentence names (type_spans), or
        the sentence itself; a sentence with a figure for both types together is one unit."""
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(x)]
        both = any(" and " in m.group("label").lower() for m in LABELLED.finditer(x))
        sp = type_spans(x) if len(named) > 1 and not both else []
        return sp or [(named[0] if len(named) == 1 else None, x, x)]

    # labelled volumes first; a denial counts against the figure's own type only (verification 3, #1)
    def labelled():
        for x in sents:
            if LOCAL.search(x):
                continue
            for _, own, seg in units(x):
                if NEGATED.search(own):
                    continue
                yield from LABELLED.finditer(seg)

    for m in labelled():
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
        if LOCAL.search(s) or any(_gal(z) == 0 for z in LABELLED.finditer(s)):
            continue
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(s)]
        spans = [u for u in units(s) if u[0] and len(named) > 1]
        for t, own, seg in spans:
            # both types in one clause: each affirmed type is its own record with its own day, its own stated times
            # and its own figure, whatever the other type carries (earlier #1; verification 3, #1)
            if affirmative(own) and not NOT_REPORT.search(own):
                x = add(t, f"MMSD's post: \"{quote.get(s, s)[:240]}\"")
                if x["day"] is None:
                    x["day"] = occurrence_day(own, ref)
                _times(x, own)
                figs = [f for f in FIGURE.finditer(seg) if not NOT_VOLUME.search(seg[max(0, f.start() - 60):f.end() + 20])]
                if x["volume_text"] is None and len(figs) == 1 and not LABELLED.search(seg):
                    x["volume"], x["volume_text"] = _gal(figs[0]), _words(figs[0].group(0))
        if spans or NOT_REPORT.search(s) and not LABELLED.search(s):
            continue
        if len(named) == 1 and affirmative(s):
            x = add(named[0], f"MMSD's post: \"{quote.get(s, s)[:240]}\"")
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
        if LOCAL.search(s):
            continue
        named = [t for t, rx in TYPE_WORDS.items() if rx.search(s)]
        spans = [u for u in units(s) if u[0] and len(named) > 1]
        rxs = (WATER_INTO, WATER_LISTED)
        if spans:
            # each affirmed type keeps the water its own words name; a denial of the other type takes nothing from it
            # (verification 3, #1)
            for t, own, _ in spans:
                if t in types and affirmative(own) and not NOT_REPORT.search(own):
                    for m in WATER_INTO.finditer(own):
                        w = _words(m.group("w"))
                        if w not in types[t]["waters"]:
                            types[t]["waters"].append(w)
            rxs = (WATER_LISTED,)
        if NEGATED.search(s):
            continue
        for rx in rxs:
            for m in rx.finditer(s):
                w = _words(m.group("w"))
                t = named[0] if len(named) == 1 else ("sso" if rx is WATER_LISTED and "sso" in types else
                                                       next(iter(types), None))
                if len(named) > 1 and rx is WATER_INTO:
                    # "a combined sewer overflow into Lincoln Creek and a separate sewer overflow into Honey Creek"
                    t = max(((m2.start(), t2) for t2, r2 in TYPE_WORDS.items() for m2 in r2.finditer(s)
                             if m2.start() < m.start()), default=(0, t))[1]
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
        other = any(rx.search(x) for t, rx in TYPE_WORDS.items() if t not in named)  # a type not reported here
        plural = not named and not other and len(types) > 1 and BOTH.search(x)
        owners = ([] if other and named else named if len(named) == 1 else list(types) if plural else
                  [next(iter(types))] if not named and len(types) == 1 else [])
        if NEGATED.search(x):
            continue                    # an expected, conditional or denied time is not a stated one (Astra P1-3)
        for t in owners:
            if types[t].get("day") is None and (len(named) == 1 or plural) and affirmative(x):
                types[t]["day"] = occurrence_day(x, ref)   # only a day the sentence ties to the overflow (earlier #2)
            _times(types[t], x)
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
            # the storm's dates are not the overflow's start: kept as the period and a lower bound only, so the status
            # engine counts from the post's own report time (Astra re-review 2026-11-15 P1-2)
            raw["started_after"] = per[0].isoformat()
            raw["start_basis"] = (f"the post gives the storm's dates (\"{per[2]}\") and no start of its own for this "
                                  "overflow: it began on or after raw.started_after; no start is recorded")
        else:
            raw["start_basis"] = ("the post gives no start for this overflow"
                                  + (" (only its end)" if x["end"] else "")
                                  + (" (only the day it was reported)" if x["reported"] and not x["end"] else "")
                                  + ": no start is recorded")
        if x["reported"]:
            raw["reported_day"], raw["reported_day_text"] = x["reported"][0].isoformat(), x["reported"][1]
            raw["reported_day_note"] = "the day the post says the overflow was reported; not its start"
        end = None
        d0 = date.fromisoformat((start or raw.get("started_after") or "")[:10]) if (start or per) else None
        first = x["start"][0] if x["start"] else (datetime(d0.year, d0.month, d0.day, tzinfo=TZ) if d0 else None)
        if x["end"] and (first is None or x["end"][0] >= first):
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
            parse_error=None if start or per or end else "no overflow date found in the post")
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


# the free-text fields of a record: scrubbed again on every write, records carried from an earlier run included
PROSE = ("title", "_type_basis", "start_basis", "end_basis", "local_overflows_text", "_no_water_reason",
         "period_text", "reported_day_text")


def rescrub(r: dict) -> dict:
    """A record with its free text scrubbed as a new read would be (Astra verification 3, #6): a record whose text
    describes a private home anywhere has every point in it removed."""
    raw = r.get("raw") or {}
    texts = [raw.get(k) for k in PROSE if isinstance(raw.get(k), str)] + \
        [x.get("label") for x in raw.get("letters") or [] if isinstance(x, dict) and isinstance(x.get("label"), str)]
    private = any(PRIVATE_PLACE.search(x) for x in texts)
    for k in PROSE:
        if isinstance(raw.get(k), str):
            raw[k] = safe_line(raw[k], private)
    for x in raw.get("letters") or []:
        if isinstance(x, dict) and isinstance(x.get("label"), str):
            x["label"] = safe_line(x["label"], private)
    return r


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
    out = sorted((rescrub(r) for r in recs.values()), key=lambda r: (r.get("started_at") or "", r["event_id"]),
                 reverse=True)
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
        # an incomplete read is not a successful one (Astra review P1-4): ok=False keeps the previous file's
        # last_ok_at, and the failed posts are listed for the next run. The records written are this run's: build()
        # carried every earlier record of a failed post unchanged, and the posts read well are kept now, so one
        # refused old post never freezes the feed or loses a new post that scrolls off (Astra re-review P1-5)
        why = "; ".join([f"{f.get('slug')}: {f.get('reason')}" for f in failed] +
                        [f"{x}: a stamped page with no report where one stood" for x in stats["posts_without_report"]])
        retry = [{k: f.get(k) for k in ("url", "slug", "title", "list_date")} for f in failed] + \
                [{k: it.get(k) for k in ("url", "slug", "title", "list_date")} for it in doc.get("items") or []
                 if it.get("slug") in stats["posts_without_report"]]
        write_events(SOURCE_ID, recs, ok=False, error=f"posts not read: {why}"[:800], meta={**meta, "retry": retry},
                     partial=True)
        print(f"{SOURCE_ID}: incomplete ({why})", file=sys.stderr)
        return 1
    meta["retry"] = []
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {json.dumps(stats)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
