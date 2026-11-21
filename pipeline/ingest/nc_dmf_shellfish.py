"""North Carolina DMF shellfish closures: the Division of Marine Fisheries' polluted area proclamations.

Source
  https://www.deq.nc.gov/about/divisions/marine-fisheries/rules-proclamations-and-size-and-bag-limits/polluted-area-proclamations
  (registry: nc-dmf-polluted-area-proclamations). DMF lists its proclamations newest first, ten to a page
  (?page=1, ?page=2, ...; 17 pages on 2026-11-16, back to February 2025), each with its number and order (a PDF), a
  one-sentence summary, the effective date, the issued date and the counties affected. DMF: polluted area
  proclamations "include temporary closures and re-openings to shellfish harvest as a result of bacteriological water
  quality, as well as changes in descriptions of permanently closed areas due to Sanitary Survey findings". The
  proclamations are orders under G.S. 113-221.1 and 15A NCAC 03H .0103. The page answers the pipeline's runner (runner
  probe 43885170112, 2026-11-16) and this project's machines.

Which proclamations make records (the site's rule)
  - A temporary closure ("This proclamation closes the following area(s) in <counties>: <areas>", effective as a
    "Shellfish Temporary Closure") is DMF's closure for bacteriological water quality, the closure that follows rain
    runoff or a sewage release: one shellfish_closure record per area it names.
  - A reopening ("returns the following area(s) to normal (closure) boundaries: <areas>") makes no record; it ends the
    closures it names (below).
  - A permanent-closure proclamation (PA-PC-<year>: "closes approximately N acres in ...", Sanitary Survey boundary
    changes) is a reclassification, not a dated closure event: left out, counted in meta.left_out.
  - A closure whose summary or effective text names a marine biotoxin (red tide), a season or resource management
    (NOT_POLLUTION) is no sign of sewage or runoff: left out, counted in meta.left_out.not_pollution. None on the
    list on 2026-11-16 (DMF's biotoxin and season closures are separate proclamations, not polluted area ones).
  - Anything else is unread (meta.unread; health false): the reader never guesses a proclamation's kind.
  DMF's list gives no cause per proclamation (raw.reason None, raw.reason_basis); the order itself (PDF) is linked.

Times (America/New_York: North Carolina lies wholly in the Eastern time zone, 49 CFR 71.4; DMF's times are local
clock times)
  - started_at: the closure's effective time as DMF states it ("effective at 7:45 a.m., Monday, October 12th, 2026"),
    time_precision minute (the day only, at "sunrise"). published_at and source_updated_at: the issued date (day).
  - End: only a later reopening proclamation that names the area ends its closure: ended_at its effective day
    (raw.ended_at_precision day: DMF reopens "at sunrise", counted to the end of that day), raw.ended_by its number.
    A reopening whose effective day is after the read is DMF's plan (raw.reopening_proclaimed), never an end until
    that day. A reopening of a portion ends only a closure of that portion in the same words ("a portion of" closed,
    "a portion of" reopened), or is noted (raw.partial_reopenings); a reopening of the whole area ends any. A closure
    that no reopening names stays as DMF left it; the status build's rule for an advisory with no end then applies
    (red 14 days from its start and issue, then shown as not reconfirmed). Absence from the list never ends anything.
  - Matching: the same area name (case and a leading "the" set aside) with a county in common (an area's own
    "(Pamlico County)" qualifier, else the proclamation's counties), in a proclamation issued later (number order
    within a year). A name DMF uses in two counties (TWO_COUNTY_NAMES), unqualified in a proclamation that lists both,
    is ambiguous: never placed and never ended (raw.ambiguous_reopenings). Only DMF's affirmative effective sentence
    is taken (EFFECTIVE_WHOLE): a negation, a condition or a postponement is unread.

Place
  A temporary closure closes DMF's Conditionally Approved-Open areas of that name. An area named whole whose name is
  one of DMF's own Conditionally Approved-Open polygons (Shellfish Growing Area Classifications layer, AREAS, a
  reviewed table), in the proclamation's counties, is a marker at a point inside that polygon (or the union of its
  parts), on the site's water record that holds it, never colouring that whole water (raw._point_extent_only). An area
  closed in part ("a portion of Newport River"), named in no polygon, or held by no water record here is listed with
  DMF's words and placed on no water (raw._placement listed_only). A model never supplies a place.

A bad read changes nothing: a failed request, a page without its closing tag, the title, the proclamation list or a
row count as expected writes ok=False and keeps every earlier record. A row that cannot be read is listed in
meta.unread (health false) while the readable rows update, and stays there, its page read again each run, until it
is read (a later run that does not read its page carries it); since only an affirmative reopening ends a closure, an
unread row can never end one. Every page but the last must list ten proclamations, or the read fails. An archive
entry that is only a date with no proclamation (the oldest page) is skipped by name (meta.skipped).

Reads: the first READ_PAGES pages and the pages of carried unread rows every run; every page the pager names when no
earlier record is held (the first run) or with --backfill. Privacy: only the proclamation list is read (the contact paragraph above it is not); every
field is cleaned before any save; the raw save is the parsed rows as JSON.

Run from pipeline/:  python -m ingest.nc_dmf_shellfish [--file p0.html [p1.html ...]] [--backfill]
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from common import error_detail
from ingest import nv_state_parks_hab as P

SOURCE_ID = "nc-dmf-polluted-area-proclamations"
URL = ("https://www.deq.nc.gov/about/divisions/marine-fisheries/rules-proclamations-and-size-and-bag-limits/"
       "polluted-area-proclamations")
AUTHORITY = "North Carolina Department of Environmental Quality, Division of Marine Fisheries (DMF), Shellfish Sanitation"
ZONE = ZoneInfo("America/New_York")
LAYER = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services/ShellfishGrowingArea/FeatureServer/0"
READ_PAGES = 3

TITLE = re.compile(r"<h1\b[^>]*>(?:\s*<[^>]+>)*\s*Polluted Area Proclamations\s*(?:</[^>]+>\s*)*</h1>", re.I)
LIST_HEAD = re.compile(r"<h2>\s*Proclamations\s*</h2>\s*<div\b[^>]*\bview-ncc-dmf-fm-proclamations\b", re.I)
ROW = re.compile(r'<div class="views-row">', re.I)
LAST_PAGE = re.compile(r'<a href="\?page=(\d+)"[^>]*title="Go to last page"', re.I)
PA_ID = re.compile(r"^PA-(?P<n>\d{1,3})-(?P<y>\d{4})$")
PC_ID = re.compile(r"^PA-PC(?:-\d+)?-\d{4}$")
CLOSE = re.compile(r"^This proclamation closes the followings? areas? in (?P<where>[^:]+):\s*(?P<list>[^.]+?)\.?$", re.I)
OPEN = re.compile(r"^This proclamation returns the following areas? to normal (?:closure )?boundaries:\s*"
                  r"(?P<list>[^.]+?)\.?$", re.I)
PERMANENT = re.compile(r"^This proclamation closes approximately\b", re.I)
# a closure for a marine biotoxin, a season or resource management is no sign of sewage or runoff: typed apart, no record
NOT_POLLUTION = re.compile(r"\b(?:red tide|biotoxin|karenia|algal|harmful algae|domoic|paralytic|neurotoxic|season|"
                           r"management|harvest limit|quota|holiday|hurricane season)\b", re.I)
EFFECTIVE = re.compile(
    r"\beffect(?:ive)?\s+(?:at\s+)?(?:(?P<sunrise>sunrise)|(?P<h>\d{1,2}):(?P<mi>\d{2})\s*(?P<ap>[ap])\.?\s*m\.?)\s*,?\s*"
    r"(?P<dow>[A-Z][a-z]+day)\s*,?\s*(?P<mon>[A-Z][a-z]+)\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?\s*[,.]?\s*(?P<y>\d{4})\b",
    re.I)
ISSUED = re.compile(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{2}|\d{4})$")
PORTION = re.compile(r"^(?:a portion of|portions of|part of|the (?:north|south|east|west)(?:ern)? (?:side|portion|part) "
                     r"of|all those waters in)\s+", re.I)       # its words are kept: a portion is matched only in the same words
COUNTY_Q = re.compile(r"\s*\((?P<c>[A-Z][A-Za-z ]+?) County\)$")
# the effective sentence must be DMF's affirmative order and end at its date (Astra review 2026-11-16 P1-8): a negation,
# a condition or a postponement ("NOT effective", ", if results allow", "postponed") is unread, never an order
EFFECTIVE_WHOLE = re.compile(
    r"^Shellfish (?:Temporary Closures?|reopenings?) effect(?:ive)?\s+(?:at\s+)?(?:sunrise|\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?)"
    r"\s*,?\s*[A-Z][a-z]+day\s*,?\s*[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?\s*[,.]?\s*\d{4}\s*\.?$", re.I)
NOT_AFFIRMED = re.compile(r"\b(?:not|no longer|unless|if|until|pending|postpon\w*|rescind\w*|cancel\w*|delay\w*|"
                          r"suspend\w*|withdr[ae]w\w*)\b", re.I)
# an archive entry that is only a date, with no proclamation (the list's oldest page, 2026-11-16): skipped by name
BARE_DATE = re.compile(r"^\d{1,2}:\d{2}\s*[AP]\.?M\.?,\s*[A-Z][a-z]+day,\s*[A-Z][a-z]+\s+\d{1,2},\s*\d{4}$", re.I)
PAGE_SIZE = 10
# names DMF uses in two counties (it adds "(Pamlico County)" in some proclamations, not in all): an unqualified one in
# a proclamation that lists both counties is ambiguous: never placed, never ended by a reopening (Astra P1-5)
TWO_COUNTY_NAMES = {"oyster creek": {"Carteret", "Pamlico"}, "bear creek": {"Onslow", "Pamlico"}}
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), start=1)}

# DMF's Conditionally Approved-Open areas a proclamation names whole -> DMF's own polygons (Shellfish Growing Area
# Classifications layer, HA_CLASS "Conditionally Approved - Open", data edited 2026-09-01; read 2026-11-16). point:
# the representative point of the polygon or of the union of its parts, 0.001 degree. water: the site's record that
# holds the area: the water DMF names where the site's record of that name runs through the area, else a polygon
# record holding the representative point and at least 60 percent of the area (shares checked 2026-11-16 against
# the water records). Areas with a polygon but no such record (Queens Creek, Newport River, North River, Jarrett Bay,
# Middle Sound, Myrtle Grove Sound and others) are not here: listed only. The keys are DMF's area names, lower case.
AREAS = {
    "bogue sound": {"objectids": [17906], "layer_name": "Bogue Sound Area", "counties": {"Carteret"},
                    "point": (34.726, -76.837), "water": "bogue-sound-nc",
                    "water_basis": "98.8 percent of DMF's Bogue Sound Area lies in the Bogue Sound record"},
    "brett bay": {"objectids": [17702], "layer_name": "Brett Bay", "counties": {"Carteret"},
                  "point": (34.829, -76.426), "water": "core-sound-nc",
                  "water_basis": "Brett Bay has no record here; 74.4 percent of the area lies in the Core Sound record"},
    "lockwoods folly river": {"objectids": [18069, 18165], "layer_name": "Lockwoods Folly River",
                              "counties": {"Brunswick"}, "point": (33.926, -78.22), "water": "lockwoods-folly-river-nc",
                              "water_basis": "DMF names the Lockwoods Folly River; its record's line runs 1.0 km "
                                             "through the area"},
    "masonboro sound": {"objectids": [18029], "layer_name": "Masonboro Sound", "counties": {"New Hanover"},
                        "point": (34.162, -77.85), "water": "masonboro-sound-nc",
                        "water_basis": "DMF names Masonboro Sound; 62.4 percent of the area lies in its record"},
    "nelson bay": {"objectids": [17630], "layer_name": "Nelson Bay", "counties": {"Carteret"},
                   "point": (34.86, -76.403), "water": "core-sound-nc",
                   "water_basis": "Nelson Bay has no record here; 82.4 percent of the area lies in the Core Sound record"},
    "ocean isle beach": {"objectids": [18076], "layer_name": "Ocean Isle Beach", "counties": {"Brunswick"},
                         "point": (33.901, -78.414), "water": "intracoastal-waterway-calabash-nc",
                         "water_basis": "90 percent of the area lies in the Intracoastal Waterway record (Calabash to "
                                        "Ocean Isle Beach)"},
    "old topsail creek": {"objectids": [17986, 18127], "layer_name": "Old Topsail Creek", "counties": {"Pender"},
                          "point": (34.422, -77.576), "water": "topsail-sound-nc",
                          "water_basis": "Old Topsail Creek has no record here; 74.9 percent of the area lies in the "
                                         "Topsail Sound record"},
    "oyster creek": {"objectids": [17622], "layer_name": "Oyster Creek", "counties": {"Carteret"},
                     "point": (34.823, -76.455), "water": "core-sound-nc",
                     "water_basis": "Oyster Creek (Carteret County) has no record here; 70 percent of the area lies "
                                    "in the Core Sound record"},
    "sanders creek": {"objectids": [18009], "layer_name": "Sanders Creek", "counties": {"Carteret"},
                      "point": (34.704, -76.97), "water": "bogue-sound-nc",
                      "water_basis": "Sanders Creek has no record here; 90.4 percent of the area lies in the Bogue "
                                     "Sound record"},
    "shallotte river": {"objectids": [18072], "layer_name": "Shallotte River", "counties": {"Brunswick"},
                        "point": (33.917, -78.371), "water": "shallotte-river-nc",
                        "water_basis": "DMF names the Shallotte River; its record's line runs 0.9 km through the area"},
    "sleepy creek": {"objectids": [17889], "layer_name": "Sleepy Creek", "counties": {"Carteret"},
                     "point": (34.727, -76.525), "water": "core-sound-nc",
                     "water_basis": "Sleepy Creek has no record here; 62.8 percent of the area lies in the Core Sound "
                                    "record"},
    "stump sound": {"objectids": [17928, 17934, 17984, 18054], "layer_name": "Stump Sound",
                    "counties": {"Onslow", "Pender"}, "point": (34.469, -77.486), "water": "stump-sound-nc",
                    "water_basis": "DMF names Stump Sound; 79.1 percent of its four parts lie in its record"},
    "tubbs inlet": {"objectids": [18141], "layer_name": "Tubbs Inlet", "counties": {"Brunswick"},
                    "point": (33.877, -78.481), "water": "intracoastal-waterway-calabash-nc",
                    "water_basis": "Tubbs Inlet has no record here; 80.6 percent of the area lies in the Intracoastal "
                                   "Waterway record (Calabash to Ocean Isle Beach)"},
}
REASON_BASIS = ("DMF's list gives no cause per proclamation; DMF says its temporary closures are made 'as a result of "
                "bacteriological water quality'; the order itself is linked (raw.order_url)")
START_BASIS = "the closure's effective time as DMF's proclamation states it, local time"
END_BASIS = ("the effective day of DMF's later proclamation that returns the area to normal boundaries (DMF reopens "
             "at sunrise: counted to the end of that day)")
PLAN_BASIS = ("DMF has proclaimed a reopening effective on a later day: DMF's plan, not an end until that day")
POINT_BASIS = ("a point inside the area: the representative point of DMF's own Conditionally Approved-Open polygon "
               "for it (Shellfish Growing Area Classifications layer, edited 2026-09-01), 0.001 degree; the marker of "
               "a part of the water, which is never coloured whole")
LISTED_ONLY_NOTE = ("an area this site has no outline or water record for (or closed only in part): listed with "
                    "DMF's words and placed on no water, so it colours none")
NO_REOPENING_NOTE = ("no later proclamation on DMF's list names this area's reopening; shown as DMF left it, under "
                     "the site's rule for an advisory with no stated end")


def text_of(fragment: str) -> str:
    return P.text_of(fragment)


def last_page(page: str) -> int:
    m = LAST_PAGE.search(page or "")
    return int(m.group(1)) if m else 0


def issued_day(s: str) -> date:
    m = ISSUED.match(s.strip().rstrip("."))
    if not m:
        raise ValueError("issued date")
    y = int(m.group("y"))
    return date(y + 2000 if y < 100 else y, int(m.group("m")), int(m.group("d")))


def effective(s: str) -> dict:
    """DMF's effective sentence -> {text, at, precision}; ValueError when no date can be read."""
    m = EFFECTIVE.search(s or "")
    if not m or m.group("mon").lower() not in MONTHS:
        raise ValueError("effective date")
    day = date(int(m.group("y")), MONTHS[m.group("mon").lower()], int(m.group("d")))
    out = {"text": s, "day": day.isoformat(), "weekday_as_given": m.group("dow")}
    if day.strftime("%A").lower() != m.group("dow").lower():
        out["weekday_mismatch"] = True        # kept as DMF wrote it; the date is the one used
    if m.group("sunrise"):
        out.update(at=day.isoformat(), precision="day", sunrise=True)
    else:
        h = int(m.group("h")) % 12 + (12 if m.group("ap").lower() == "p" else 0)
        out.update(at=datetime(day.year, day.month, day.day, h, int(m.group("mi")), tzinfo=ZONE).isoformat(),
                   precision="minute")
    return out


def split_areas(lst: str) -> list[dict]:
    """'A portion of Bay River and Jones Bay' -> [{text, key, portion, county}], DMF's words kept."""
    out = []
    for raw in re.split(r",\s*(?:and\s+)?|\s+and\s+", lst or ""):
        t = re.sub(r"\s+", " ", raw).strip().rstrip(".").strip()
        if not t:
            continue
        q = PORTION.match(t)
        qualifier = re.sub(r"\s+", " ", q.group(0)).strip().lower() if q else ""
        name = PORTION.sub("", t)
        cq = COUNTY_Q.search(name)
        county = P.clean_field(cq.group("c").strip(), "place") if cq else None
        # the key comes from the cleaned name: a name withheld for privacy never reaches a key or an id (Astra P1-1)
        name = P.clean_field(COUNTY_Q.sub("", name), "place")
        key = re.sub(r"^the\s+", "", re.sub(r"\s+", " ", name).strip().lower())
        out.append({"text": P.clean_field(t, "place"), "key": key, "portion": bool(q), "qualifier": qualifier,
                    "county": county})
    return out


def counties_of(s: str) -> list[str]:
    s = re.sub(r"\s+Count(?:y|ies)\b", "", (s or "").strip().rstrip("."), flags=re.I)
    return [c.strip() for c in re.split(r",\s*(?:and\s+)?|\s+and\s+", s) if c.strip()]


def parse_row(block: str) -> dict:
    """One proclamation of the list; ValueError (with a reason) for a row the reader cannot take whole."""
    h = re.search(r"<h3>\s*<a href=\"(?P<href>[^\"]+)\">(?P<id>[^<]+)</a>\s*</h3>", block, re.I)
    if not h:
        raise ValueError("a row with no proclamation number")
    pid = text_of(h.group("id")).upper()
    ps = [text_of(x) for x in re.findall(r"<p>(.*?)</p>", block, re.S | re.I)]
    labelled = {}
    for p in ps:
        m = re.match(r"^(Effective Date|Issued Date|Counties Affected):\s*(.*)$", p)
        if m:
            labelled[m.group(1)] = m.group(2).strip()
    body = [p for p in ps if p and not re.match(r"^(Effective Date|Issued Date|Counties Affected):", p)]
    if not body or set(labelled) != {"Effective Date", "Issued Date", "Counties Affected"}:
        raise ValueError("a row without its summary, effective date, issued date and counties")
    summary = body[0]
    try:
        issued = issued_day(labelled["Issued Date"])
    except ValueError:
        raise ValueError("an issued date the reader cannot take") from None
    row = {"id": pid, "order_url": h.group("href"), "summary": P.clean_text(summary)[0], "issued": issued.isoformat(),
           "counties": [P.clean_field(c, "place") for c in counties_of(labelled["Counties Affected"])],
           "effective_text": P.clean_text(labelled["Effective Date"])[0]}
    if PC_ID.match(pid) or PERMANENT.match(summary):
        row.update(kind="permanent_boundary", areas=[])
        return row
    pm = PA_ID.match(pid)
    if not pm:
        raise ValueError("a proclamation number the reader cannot take")
    row.update(year=int(pm.group("y")), number=int(pm.group("n")))
    eff = labelled["Effective Date"]
    c, o = CLOSE.match(summary), OPEN.match(summary)
    if len(body) != 1:
        raise ValueError("a summary of more than one paragraph")
    if c and NOT_POLLUTION.search(summary + " " + eff):
        row.update(kind="not_pollution", areas=[])
        return row
    if (c or o) and (NOT_AFFIRMED.search(summary) or NOT_AFFIRMED.search(eff) or not EFFECTIVE_WHOLE.match(eff.strip())):
        raise ValueError("wording the reader does not take as DMF's affirmative order (a negation, a condition or an "
                         "unknown form)")
    if c and re.search(r"\bTemporary Closures?\b", eff, re.I):
        kind, lst = "temporary_closure", c.group("list")
    elif o and re.search(r"\breopenings?\b", eff, re.I):
        kind, lst = "reopening", o.group("list")
    else:
        raise ValueError("a proclamation the reader cannot type (not a temporary closure or a reopening)")
    try:
        row["effective"] = effective(eff)
    except ValueError:
        raise ValueError("an effective date the reader cannot take") from None
    row["effective"]["text"] = row["effective_text"]
    row.update(kind=kind, areas=split_areas(lst))
    if not row["areas"]:
        raise ValueError("a proclamation that names no area")
    return row


def parse(page: str, n: int = 0) -> dict:
    """{rows, unread, last_page}; ValueError for a page that is not a complete reading of the list."""
    if not re.search(r"</html\s*>", page or "", re.I):
        raise ValueError("the page is not complete (no closing html tag)")
    if len(TITLE.findall(page)) != 1:
        raise ValueError("the page's title is not Polluted Area Proclamations")
    heads = list(LIST_HEAD.finditer(page))
    if len(heads) != 1:
        raise ValueError("the proclamation list is not on the page once")
    after = page[heads[0].end():]
    content = re.search(r'<div class="view-content[^"]*">(?P<body>.*?)(?:<nav\b|</div>\s*</div>\s*</div>\s*'
                        r'</div>\s*</div>\s*</div>\s*$)', after, re.S | re.I)
    if not content:
        raise ValueError("the proclamation list's rows are not on the page")
    starts = [m.start() for m in ROW.finditer(content.group("body"))]
    if not starts:
        raise ValueError("the proclamation list has no row")
    blocks = [content.group("body")[a:b] for a, b in zip(starts, starts[1:] + [len(content.group("body"))])]
    rows, unread, skipped = [], [], []
    for i, b in enumerate(blocks, start=1):
        bare = text_of(b)
        if not re.search(r"<h3\b", b, re.I) and BARE_DATE.match(bare):
            skipped.append({"page": n, "row": i, "text": bare, "reason": "an archive entry with a date and no proclamation"})
            continue
        try:
            rows.append(parse_row(b))
        except ValueError as e:
            h = re.search(r">(PA-[A-Z0-9-]+)<", b)
            unread.append({"page": n, "row": i, "id": h.group(1) if h else None, "reason": error_detail(e)})
    return {"rows": rows, "unread": unread, "skipped": skipped, "last_page": last_page(after), "count": len(blocks)}


def saved_form(parsed: list[dict]) -> str:
    """What the raw save keeps: the parsed list as JSON; never the page's markup."""
    return json.dumps(P.deep_clean({"url": URL, "pages": parsed}), ensure_ascii=False, indent=1)


def order(row_or_raw: dict) -> tuple:
    return (row_or_raw.get("year") or 0, row_or_raw.get("number") or 0)


def area_counties(area: dict, row: dict) -> tuple[set[str], bool]:
    """(the counties the area can lie in, ambiguous): its own "(X County)" qualifier, else the proclamation's counties;
    a name DMF uses in two counties, both listed and no qualifier, is ambiguous (Astra P1-5)."""
    if area.get("county"):
        return {area["county"]}, False
    counties = set(row.get("counties") or [])
    two = TWO_COUNTY_NAMES.get(area["key"])
    if two:
        cand = two & counties
        return (cand, False) if len(cand) == 1 else (cand or counties, True)
    return counties, False


def srid_of(row: dict, area: dict) -> str:
    return (f"{row['id']}:{P.slug(area['key'])}" + (f"-{P.slug(area['county'])}" if area.get("county") else "")
            + (f"-{P.slug(area['qualifier'])}" if area.get("qualifier") else ""))


def place(area: dict, row: dict) -> dict | None:
    a = AREAS.get(area["key"])
    counties, ambiguous = area_counties(area, row)
    if a is None or area["portion"] or ambiguous or not a["counties"] <= counties:
        return None
    return a


def pages_to_read(unread: list[dict] | None, last: int) -> list[int]:
    """The first READ_PAGES pages and every page an earlier read left a row unread on (Astra P1-7)."""
    extra = {u["page"] for u in unread or [] if isinstance(u.get("page"), int) and 0 <= u["page"] <= last}
    return sorted(set(range(min(READ_PAGES, last + 1))) | extra)


def build(pages, fetched: str, previous: list[dict], previous_unread: list[dict] | None = None
          ) -> tuple[list[dict], dict]:
    """pages: the pages read, a list (page 0, 1, ...) or {page number: html}. previous_unread: meta.unread of the
    last run; a row unread on a page not read again stays unread (health false) until its page is read."""
    pages = dict(enumerate(pages)) if isinstance(pages, list) else dict(pages)
    parsed = {n: parse(pg, n) for n, pg in sorted(pages.items())}
    last = parsed[0]["last_page"] if 0 in parsed else max(parsed)
    for n, p in parsed.items():
        if n != last and p["count"] != PAGE_SIZE:
            # a page short of rows is a read that missed a proclamation (Astra P1-6): fail the read, change nothing
            raise ValueError(f"page {n} lists {p['count']} proclamations, not {PAGE_SIZE}")
    rows = [r for p in parsed.values() for r in p["rows"]]
    unread = [u for p in parsed.values() for u in p["unread"]]
    unread += [dict(u, carried=True) for u in previous_unread or []
               if isinstance(u.get("page"), int) and u["page"] not in parsed]
    read_day = datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZONE).date()
    seen_ids = set()
    for r in rows:
        if r["id"] in seen_ids:
            unread.append({"page": None, "row": None, "id": r["id"], "reason": "a proclamation listed twice"})
        seen_ids.add(r["id"])
    future = [r for r in rows if date.fromisoformat(r["issued"]) > read_day + timedelta(days=1)]
    for r in future:        # an issued date after the read is a misreading or a typing error: not taken
        unread.append({"page": None, "row": None, "id": r["id"], "reason": "an issued date after the read"})
    rows = [r for r in rows if r not in future]
    prev_by = {p.get("source_record_id"): p for p in previous}
    records: dict[str, dict] = {}
    opened = 0
    for row in sorted((r for r in rows if r["kind"] == "temporary_closure"), key=order):
        done = set()
        for area in row["areas"]:
            srid = srid_of(row, area)
            if srid in done:
                continue
            done.add(srid)
            prev = prev_by.get(srid)
            praw = (prev or {}).get("raw") or {}
            opened += prev is None
            spot = place(area, row)
            raw = {"proclamation": row["id"], "year": row["year"], "number": row["number"], "order_url": row["order_url"],
                   "summary": row["summary"], "area_text": area["text"], "area_key": area["key"],
                   "portion": area["portion"], "portion_words": area["qualifier"] or None,
                   "county_qualifier": area["county"], "counties": row["counties"],
                   "resolved_counties": sorted(area_counties(area, row)[0]),
                   "county_ambiguous": area_counties(area, row)[1],
                   "effective": row["effective"], "issued": row["issued"], "reason": None, "reason_basis": REASON_BASIS,
                   "start_basis": START_BASIS, "time_zone": "America/New_York", "state": "NC", "page_url": URL,
                   "_first_seen_at": praw.get("_first_seen_at") or fetched}
            for k in ("ended_by", "end_text", "end_basis", "ended_at_precision", "reopening_proclaimed",
                      "partial_reopenings"):
                if praw.get(k) is not None:
                    raw[k] = praw[k]
            if spot:
                lat, lon = spot["point"]
                raw.update(_point_extent_only=True, point_basis=POINT_BASIS,
                           area_polygon={"layer": LAYER, "objectids": spot["objectids"], "layer_name": spot["layer_name"],
                                         "edition": "data edited 2026-09-01"},
                           water_basis=spot["water_basis"])
                slugs, match = [spot["water"]], "geometry"
            else:
                lat = lon = None
                raw.update(_placement="listed_only", placement_note=LISTED_ONLY_NOTE)
                slugs, match = [], "none"
            where = area["county"] or ", ".join(row["counties"])
            records[srid] = event(
                source_id=SOURCE_ID, source_record_id=srid, event_type="shellfish_closure",
                status=(prev or {}).get("status") if (prev or {}).get("status") == "advisory_lifted" else "advisory_active",
                waterbody_text=area["text"], water_slugs=slugs, water_match=match,
                lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=None,
                started_at=row["effective"]["at"], ended_at=(prev or {}).get("ended_at")
                if (prev or {}).get("status") == "advisory_lifted" else None,
                time_precision=row["effective"]["precision"], published_at=row["issued"],
                source_updated_at=row["issued"], fetched_at=fetched, authority=AUTHORITY, source_url=row["order_url"],
                raw=raw, advice_text=(f"Shellfish harvest closure (North Carolina DMF proclamation {row['id']}): "
                                      f"{area['text']} ({where}), a temporary closure. DMF: {row['effective_text']} "
                                      f"Issued {row['issued']}."))
    # carried closures: kept as they were (never ended or dropped by their absence from this read)
    for p in previous:
        sid = p.get("source_record_id")
        if sid not in records:
            records[sid] = P.recleaned(p)
    # reopenings: only an affirmative, later proclamation that names the area ends its closure
    reopenings = sorted((r for r in rows if r["kind"] == "reopening"), key=order)
    lifted = 0
    for sid, rec in records.items():
        if rec.get("status") != "advisory_active":
            continue
        raw = dict(rec.get("raw") or {})
        mine = set(raw.get("resolved_counties") or raw.get("counties") or [])
        hit = None
        pending = raw.get("reopening_proclaimed")
        for ro in reopenings:
            if order(ro) <= order(raw):
                continue
            for a in ro["areas"]:
                theirs, their_amb = area_counties(a, ro)
                if a["key"] != raw.get("area_key") or not (theirs & mine):
                    continue
                if raw.get("county_ambiguous") or their_amb:
                    # which county's area is meant cannot be told: never an end (Astra P1-5)
                    amb = list(raw.get("ambiguous_reopenings") or [])
                    if ro["id"] not in amb:
                        amb.append(ro["id"])
                    raw["ambiguous_reopenings"] = amb
                    continue
                if a["qualifier"] and a["qualifier"] != (raw.get("portion_words") or ""):
                    # a reopening of a portion ends only a closure of that portion in the same words (Astra P1-4)
                    pr = list(raw.get("partial_reopenings") or [])
                    if ro["id"] not in [x.get("proclamation") for x in pr]:
                        pr.append({"proclamation": ro["id"], "text": a["text"], "effective": ro["effective"]["text"]})
                    raw["partial_reopenings"] = pr
                    continue
                hit = hit or {"proclamation": ro["id"], "order_url": ro["order_url"], "effective_day":
                              ro["effective"]["day"], "effective_text": ro["effective"]["text"], "issued": ro["issued"],
                              "text": a["text"]}
            if hit:
                break
        hit = hit or pending
        if hit and date.fromisoformat(hit["effective_day"]) <= read_day:
            if date.fromisoformat(hit["effective_day"]) < date.fromisoformat(str(rec.get("started_at"))[:10]):
                raw["reopening_before_start"] = hit      # not an end: a reopening dated before the closure
            else:
                raw.pop("reopening_proclaimed", None)
                raw.pop("no_reopening_note", None)
                raw.update(ended_by=hit["proclamation"], end_text=hit["effective_text"], ended_at_precision="day",
                           end_basis=END_BASIS, ended_by_order_url=hit.get("order_url"))
                rec = dict(rec, status="advisory_lifted", ended_at=hit["effective_day"])
                rec["advice_text"] = (rec.get("advice_text") or "") + \
                    f" Reopened by DMF proclamation {hit['proclamation']}: {hit['effective_text']}"
                lifted += 1
        elif hit:
            raw.update(reopening_proclaimed=dict(hit, basis=PLAN_BASIS))
        else:
            raw["no_reopening_note"] = NO_REOPENING_NOTE if not raw.get("ambiguous_reopenings") else (
                "a later proclamation names an area of this name, but which county's area each means cannot be told: "
                "shown as DMF left it, under the site's rule for an advisory with no stated end")
        rec["raw"] = raw
        records[sid] = rec
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    active = [r for r in out if r["status"] == "advisory_active"]
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "pages_read": sorted(parsed),
            "pages_listed": last + 1,
            "proclamations": len(rows) + len([u for p in parsed.values() for u in p["unread"]]),
            "skipped": [s for p in parsed.values() for s in p["skipped"]],
            "newest": max((r for r in rows if r.get("year")), key=order, default={}).get("id"),
            "newest_issued": max((r["issued"] for r in rows), default=None),
            "temporary_closures": sum(1 for r in rows if r["kind"] == "temporary_closure"),
            "reopenings": len(reopenings),
            "left_out": {"permanent_boundary": sorted(r["id"] for r in rows if r["kind"] == "permanent_boundary"),
                         "not_pollution": sorted(r["id"] for r in rows if r["kind"] == "not_pollution"),
                         "rule": "a permanent-closure proclamation (Sanitary Survey boundary changes) is a "
                                 "reclassification, not a dated closure; a closure for a marine biotoxin, a season or "
                                 "resource management is no sign of sewage or runoff: neither is a record"},
            "unread": unread, "opened": opened, "lifted_this_read": lifted, "advisory_active": len(active),
            "listed_only": sorted({r["raw"]["area_text"] for r in active if r["raw"].get("_placement") == "listed_only"}),
            "no_reopening_named": sorted(r["source_record_id"] for r in active if r["raw"].get("no_reopening_note")
                                         and not r["raw"].get("ambiguous_reopenings")),
            "held_county_ambiguous": sorted(r["source_record_id"] for r in active if r["raw"].get("ambiguous_reopenings")),
            "cadence": f"the first {READ_PAGES} pages of the list read every run; DMF issues a proclamation for each "
                       "closure and reopening",
            "coverage": "North Carolina's coastal shellfish growing areas: every temporary closure and reopening "
                        "DMF proclaims"}
    return out, meta


def fetch(n: int) -> str:
    r = requests.get(URL + (f"?page={n}" if n else ""), headers=HEADERS, timeout=(30, 120))
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
        prev = doc.get("records", [])
        prev_unread = (doc.get("meta") or {}).get("unread") or []
        if "--file" in argv:
            files = [a for a in argv[argv.index("--file") + 1:] if not a.startswith("--")]
            pages = [Path(f).read_text(errors="replace") for f in files]
        else:
            first = fetch(0)
            last = last_page(first)
            want = list(range(last + 1)) if ("--backfill" in argv or not prev) else pages_to_read(prev_unread, last)
            pages = {0: first}
            for n in want:
                if n not in pages:
                    time.sleep(1)
                    pages[n] = fetch(n)
        recs, meta = build(pages, fetched, prev, prev_unread)
        if "--file" not in argv:
            save_raw(SOURCE_ID, saved_form([parse(pg, n) for n, pg in sorted(pages.items())]), "json")
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        P.write_refused(SOURCE_ID, P.safe_error(e), EVENTS_DIR)
        print(f"{SOURCE_ID}: FAILED {P.safe_error(e)}", file=sys.stderr)
        return 1
    meta = P.deep_clean(meta)
    if meta["unread"]:
        why = "; ".join(f"{u.get('id') or 'row ' + str(u.get('row'))}: {u['reason']}" for u in meta["unread"])
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error=f"unread rows: {why}", meta=meta)
        print(f"{SOURCE_ID}: PARTIAL {len(meta['unread'])} row(s) unread -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['proclamations']} proclamations on {len(meta['pages_read'])} page(s), newest "
          f"{meta['newest']}; {len(recs)} records, {meta['advisory_active']} active -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
