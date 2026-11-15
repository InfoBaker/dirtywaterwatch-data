"""Iowa DNR news releases on wastewater discharges -> data/build/events/ia-dnr-news-releases.json.

Source
  The Iowa Department of Natural Resources' "Advisory" news topic (registry ia-dnr-news-releases): its RSS feed
  https://www.iowadnr.gov/topics/203/feed (the ten newest releases of the topic) every run, and with --backfill the
  topic's listing pages https://www.iowadnr.gov/topics/advisory?page=0..3 (every release of the topic since 2023).
  DNR publishes a release when a spill or discharge reaches a water and it wants the public told (567 IAC 63.6 lets
  DNR decide whether an unanticipated bypass needs public notice); most releases of the topic are manure, fuel,
  fertilizer, fish kills and air quality. Five releases of the topic from November 2024 to October 2026 concern a
  municipal wastewater discharge (Sioux City's Floyd lift station, Story City's treatment plant, Keokuk's collection
  system through a combined sewer outfall, and the October 2026 statewide notice of flood bypasses with a biosolids
  runoff to Cedar Creek).

Which releases (rules only)
  - The title names wastewater, sewage, a sewer or a bypass (TITLE); the release is read once (its page, saved
    scrubbed) and kept when its text names a municipal system (MUNICIPAL: a city, a treatment plant, a lift station,
    a collection system, a sewer, a lagoon, biosolids). A release about a company's process wastewater (a meat
    plant's valve) is not a sewage report: counted in meta.not_municipal with its title, no record.
  - A release with county-headed sections ("WAPELLO COUNTY - ...") is split: one record per section, and one for the
    statewide part when it reports bypasses (placed nowhere: it names no community). Otherwise one record.

Records
  - event_type: a statewide part -> bypass; a combined sewer outfall named -> cso; biosolids or sludge -> sso (material "sewage sludge /
    biosolids", as Ohio's spills); a treatment plant bypass -> plant_bypass; a lift station, a line, a manhole or a
    collection system -> sso; otherwise bypass.
  - Times (America/Chicago; the year is the release's, or the year before for a month after the release's):
    published_at the release's date (day; DNR's page stamps every release at noon UTC, not a time); reported_at the
    day DNR "was notified" or "contacted" when the text gives it; started_at the date (and time) the text says the
    discharge began ("On Saturday, April 26th around 2:00 pm, ... began bypassing"), else none: a time with no date
    ("The discharge began around 10:15 a.m.") stays in raw.start_text, and the publication date is never a start;
    ended_at the date and time the text says it ended ("ended April 27th around 4 p.m."), raw.ended_at_precision.
    Status ended when the text says it ended or stopped, else unknown (an "ongoing" bypass is ongoing at the release,
    not now: raw.at_release).
  - Operator: "by the City of X", "at the City of X" or "from the City of X" (the system's owner), else the treatment
    plant the text names ("the Story City wastewater treatment plant"), else none: a town named only as a landmark
    ("northeast of the City of Kirkville") is not the operator.
  - Water: the first water the text says the discharge went into, entered or reached (WATER), as written; the others
    in raw.other_waters and raw._also_named_waters, on which the status build places the same record (one report on
    each water). No point: placed by the names and the county only, never by a plant's receiving water.
  - Volume: an estimate the text gives ("An estimated 1.5 million gallons"), else unknown.
  - DNR's advice to the public ("Downstream recreational users should take caution and avoid the area") is quoted in
    advice_text as DNR's.
  - Identity: source_record_id the release's path (and the section's county). A release DNR edits is read again only
    when its RSS item changes; records stay when it leaves the feed.
  Privacy: only the release's body is read and saved, after the scrub (phones, emails, house numbers).

Run from pipeline/: python -m ingest.ia_dnr_news [--backfill] [--rss-file f.xml] [--article-file PATH=page.html ...]
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, event, now_iso, parse_volume_gal, read_json, save_raw, scrub_text, \
    strip_house_numbers, write_events, write_json
from ingest.ia_id_privacy import scrub_sentences

SOURCE_ID = "ia-dnr-news-releases"
SITE = "https://www.iowadnr.gov"
RSS = SITE + "/topics/203/feed"
LISTING = SITE + "/topics/advisory?page={n}"
BACKFILL_PAGES = 4
STATE_PATH = BUILD_DIR / "ia-dnr-news-state.json"
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
AUTHORITY = "Iowa Department of Natural Resources (news release)"
TITLE = re.compile(r"wastewater|sewage|sewer|bypass", re.I)
MUNICIPAL = re.compile(r"\bcity of\b|treatment plant|\bWWTP\b|lift station|collection system|\bsewer|sewage|lagoon|"
                       r"biosolids|wastewater bypass", re.I)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
MON = "|".join(MONTHS)
WATER = re.compile(r"\b(?:into|to|enter(?:s|ed)?|reach(?:es|ed|ing)?|outlets to)\s+(?:the\s+)?"
                   r"((?:[A-Z][a-z]+\s+){1,3}(?:River|Creek|Channel|Lake|Slough|Ditch|Branch|Run))\b")
SECTION = re.compile(r"^([A-Z][A-Z .']+ COUNTY)\s*(?:[\u2013\u2014-]\s*|$)", re.M)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "a half": 0.5, "half a": 0.5}


def _text(fragment: str) -> str:
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment or "", flags=re.S | re.I)
    s = re.sub(r"<(?:br|p|li|h\d|div)\b[^>]*>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return "\n".join(x for x in (re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")) if x)


def parse_rss(xml: str) -> list[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        g = lambda k: htmllib.unescape((re.search(rf"<{k}>(.*?)</{k}>", it, re.S) or [None, ""])[1]).strip()  # noqa: E731
        link = g("link")
        if not link:
            continue
        try:
            pub = parsedate_to_datetime(g("pubDate")).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            pub = None
        out.append({"title": _text(g("title")), "url": link, "rss_pubdate": pub})
    return out


def parse_listing(page: str) -> list[dict]:
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href="(/news-release/[^"]+)"[^>]*>(.*?)</a>', page or "", re.S):
        url, title = SITE + m.group(1), _text(m.group(2))
        if url in seen or not title:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "rss_pubdate": None})
    return out


def parse_article(page: str) -> dict:
    """{title, date, body}; ValueError when the page is not a release."""
    t = _text(page)
    m = re.search(rf"\n(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), ({MON}) (\d{{1,2}}), (\d{{4}})\n"
                  r"News Release\n", t)
    if not m:
        raise ValueError("no release date on the page")
    title = t[:m.start()].split("\n")[-1].strip()
    body = t[m.end():]
    body = re.sub(r"^Image\n", "", body)
    end = re.search(r"\nTo report a release after hours|Secondary Navigation Menu", body)
    body = body[:end.start()] if end else body[:6000]
    d = date(int(m.group(3)), MONTHS.index(m.group(1)) + 1, int(m.group(2)))
    return {"title": scrub_sentences(strip_house_numbers(scrub_text(title))), "date": d.isoformat(),
            "body": scrub_sentences(strip_house_numbers(scrub_text(body.strip())))}


def _year_for(month: int, release: date) -> int:
    return release.year - 1 if month > release.month else release.year


def _when(text: str, release: date, pattern: str) -> tuple[str | None, str | None, str | None]:
    """(ISO, precision, the words) of the first date (and time) the pattern finds before its verb."""
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None, None, None
    mon, day = MONTHS.index(m.group("mon").capitalize()) + 1, int(m.group("day"))
    y = _year_for(mon, release)
    hh = m.groupdict().get("h")
    try:
        if hh:
            h = int(hh) % 12 + (12 if (m.group("ap") or "").lower().startswith("p") else 0)
            v = datetime(y, mon, day, h, int(m.group("mi") or 0), tzinfo=TZ).isoformat()
            return v, "minute", m.group(0)
        return datetime(y, mon, day, tzinfo=TZ).date().isoformat(), "day", m.group(0)
    except ValueError:
        return None, None, None


DAY = rf"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?(?P<mon>{MON})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
TIME = r"(?:,?\s*(?:around|at|about)\s+(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>[ap])\.?\s*m\.?)?"
NOTIFIED = rf"\bOn\s+{DAY}\b[^.]*?\b(?:was|were|been|has been)\s+(?:notified|contacted)"
NOTIFIED_ALT = rf"(?:notified|contacted)[^.]*?\bon\s+{DAY}"
STARTED = rf"\bOn\s+{DAY}{TIME}\b,?[^.]*?\bbegan\b"
ENDED = rf"\bended\s+(?:on\s+)?{DAY}{TIME}"


# a statement that is negated or only conditional or expected is not a completed one (lessons 1): "has not been
# stopped", "will be lifted when", "is expected to end", "if results allow", "until"
NOT_DONE = re.compile(r"(?i)\b(?:not|n't|no longer|never|will|would|could|should|may|might|expected|anticipated|"
                      r"planned|once|until|unless|if|when)\b")
STOP_WORDS = re.compile(r"\b(?:has|have|was|were)\s+(?:been\s+)?(?:stopped|halted|ended)\b|\bended\b", re.I)
CSO_DENIED = re.compile(r"(?i)\b(?:no|not|non|never|nor|without)\b[\s-]+(?:\w+\s+){0,3}?(?:a\s+)?combined sewer")
SSO_AFFIRMED = re.compile(r"(?i)\b(?:sanitary|separate)\s+sewer\s+overflow")


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n", text or "") if s.strip()]


def affirmed(text: str, pattern) -> bool:
    """True when a sentence states it and that sentence is neither negated nor conditional."""
    return any(pattern.search(s) and not NOT_DONE.search(s) for s in sentences(text))


def classify(text: str) -> tuple[str, str]:
    if re.search(r"combined sewer", CSO_DENIED.sub(" ", text), re.I):
        return "cso", "sewage"
    if re.search(r"biosolids|sludge", text, re.I):
        return "sso", "sewage sludge / biosolids"
    if re.search(r"treatment plant|\bWWTP\b|treatment facility", text, re.I) and re.search(r"bypass", text, re.I):
        return "plant_bypass", "sewage"
    if re.search(r"lift station|collection system|manhole|sewer main|\bline\b", text, re.I):
        return "sso", "sewage"
    return "bypass", "sewage"


def record_from(text: str, art: dict, url: str, sid: str, county: str | None, statewide: bool, at: str) -> dict:
    release = date.fromisoformat(art["date"])
    et, material = classify(text)
    if statewide:
        et = "bypass"           # the statewide part names no system: a bypass whose place the release does not say
    waters = []
    for m in WATER.finditer(text):
        w = m.group(1).strip()
        if w not in waters and not re.match(r"(?i)(the|a|an)\s", w):
            waters.append(w)
    rep, _, rep_words = _when(text, release, NOTIFIED)
    if not rep:
        rep, _, rep_words = _when(text, release, NOTIFIED_ALT)
    start, sp, start_words = _when(text, release, STARTED)
    end, ep, end_words = _when(text, release, ENDED)
    if end and NOT_DONE.search(next((s for s in sentences(text) if end_words and end_words in s), "")):
        end, ep, end_words = None, None, None           # "is expected to have ended April 27": not an end
    vol = re.search(r"estimated\s+(?:that\s+)?(?:nearly\s+|about\s+|approximately\s+)?"
                    r"([\d.,]+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(million\s+)?gallons", text, re.I)
    gal, flag = (None, "unknown")
    vtext = "unknown"
    if vol:
        n = vol.group(1).lower()
        num = NUMBER_WORDS.get(n) or float(n.replace(",", "") or 0)
        gal = int(num * 1_000_000) if vol.group(2) else int(num)
        flag, vtext = "estimated", vol.group(0)
    stopped = bool(end) or affirmed(text, STOP_WORDS)
    advice = [s.strip() for s in re.split(r"(?<=[.!])\s+", text)
              if re.search(r"\bavoid\b|stay out|take caution|advised", s, re.I)]
    cm = re.search(r"\bin\s+((?:[A-Z][a-z]+\s+){1,2})County\b", text) or \
        re.search(r"\bin\s+((?:[A-Z][a-z]+\s+){1,2})County\b", art.get("title") or "")
    county = county or (f"{cm.group(1).strip()} County" if cm else None)
    city = re.search(r"\b(?:by|at|from) the City of ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text)
    plant = re.search(r"\b(?:the\s+)?([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+wastewater treatment plant", text)
    # the operator is the operator row of the city that owns the system (data/dischargers.json), named from the
    # permittee; a treatment plant named by its town is that town's row; otherwise none (the plant stays in raw)
    town = city.group(1) if city else (plant.group(1) if plant else None)
    op = operators().get(f"city of {town}".lower()) if town else None
    operator = op[1] if op else None
    tm = re.search(r"\b(?:discharge|bypass|release)\s+began\s+(?:around|at|about)\s+\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m\.?", text, re.I)
    raw = {"release_title": art["title"], "release_date": art["date"], "text": text, "county": county, "state": "IA",
           "system_owner_as_written": (f"City of {city.group(1)}" if city else (f"{plant.group(1)} wastewater treatment plant"
                                                                       if plant else None)),
           "statewide": statewide, "other_waters": waters[1:], "time_zone": TZ_NAME,
           "timezone_note": "Central time; the year is the release's", "reported_words": rep_words,
           "start_words": start_words, "end_words": end_words,
           "start_text": tm.group(0) if (tm and not start) else None,
           "at_release": ("ongoing" if re.search(r"\bongoing\b", text, re.I) and not stopped else None),
           "date_basis": ("the release's date is its publication, never the discharge's start; a start or end is the "
                          "one the text gives")}
    if end:
        raw["ended_at_precision"] = ep
    if statewide:
        raw["placement"] = "the release names no community or water for these bypasses: placed on no water"
    elif waters[1:]:
        # each further water the release says the discharge reached is placed too, on the one record (build/status.py
        # raw._also_named_waters; Astra 2026-11-15 P2-1)
        raw["_also_named_waters"] = list(waters[1:])
    raw["_placement"] = "own_place_only"        # never by a plant's receiving water (Astra 2026-11-15 P2-4)
    return event(source_id=SOURCE_ID, source_record_id=sid, event_type=et, status="ended" if stopped else "unknown",
                 discharger_name=operator, discharger_id=op[0] if op else None, waterbody_text=None if statewide else (waters[0] if waters else None),
                 started_at=start, ended_at=end, time_precision=sp or ("day" if rep else None), reported_at=rep,
                 published_at=art["date"], source_updated_at=None, fetched_at=at, material=material, volume_gal=gal,
                 volume_text=vtext, estimate_flag=flag, authority=AUTHORITY,
                 advice_text=(f"Iowa DNR: “{' '.join(advice)}”" if advice else None),
                 advice_window_hours=None, advice_window_basis=None, source_url=url, raw=raw)


_OPERATORS: dict | None = None


def operators() -> dict[str, tuple[str, str]]:
    """{'city of x': (row id, name)} of Iowa's operator rows whose name is a city's."""
    global _OPERATORS
    if _OPERATORS is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
        _OPERATORS = {r["name"].lower(): (r["id"], r["name"]) for r in rows
                      if isinstance(r, dict) and r.get("state") == "IA" and r.get("name", "").startswith("City of ")}
    return _OPERATORS


def split_types(rec_text: str) -> list[str]:
    """Both a combined and a separate sewer overflow affirmed in the text: two records (lessons 11), else one."""
    t = CSO_DENIED.sub(" ", rec_text)
    if re.search(r"combined sewer", t, re.I) and SSO_AFFIRMED.search(t):
        return ["cso", "sso"]
    return [""]


def scrub_title(t: str | None) -> str | None:
    """A release's title through the same scrub as its body (a title can carry a name or a telephone number)."""
    return scrub_sentences(strip_house_numbers(scrub_text(t))) if t else t


def records_for(art: dict, url: str, at: str) -> list[dict]:
    # the scrub again on what the state file carried, the title included (Astra 2026-11-15 P1-5)
    art = {**art, "body": scrub_sentences(art["body"]), "title": scrub_title(art.get("title"))}
    out = []
    for r in _records_for(art, url, at):
        kinds = split_types(r["raw"]["text"])
        if kinds == [""]:
            out.append(r)
            continue
        for k in kinds:
            sid = r["source_record_id"] + ("" if k == "cso" else f"#{k}")
            out.append(event(**{**{f: r.get(f) for f in r if f not in ("event_id", "source_record_id", "event_type",
                                                                         "raw")},
                                "source_record_id": sid, "event_type": k, "raw": {**r["raw"], "type_basis":
                                f"the release names a combined and a separate sewer overflow: this record is the {k}"}}))
    return out


def _records_for(art: dict, url: str, at: str) -> list[dict]:
    body = art["body"]
    path = url.split("/news-release/")[-1]
    heads = list(SECTION.finditer(body))
    if not heads:
        return [record_from(body, art, url, path, None, False, at)]
    out = []
    intro = body[:heads[0].start()]
    if re.search(r"bypass", intro, re.I):
        out.append(record_from(intro, art, url, path, None, True, at))
    for i, h in enumerate(heads):
        sec = body[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)].lstrip(" \n–—-")
        county = h.group(1).title()
        out.append(record_from(sec, art, url, f"{path}#{county.lower().replace(' ', '-')}", county, False, at))
    return out


def get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=(20, 120))
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    files = {}
    for i, a in enumerate(argv):
        if a == "--article-file":
            k, _, v = argv[i + 1].partition("=")
            files[k] = Path(v).read_text()
    state = read_json(STATE_PATH, {}) or {}
    arts = state.setdefault("articles", {})
    for a in arts.values():                     # carried titles scrubbed again before anything is saved (lessons 6)
        if isinstance(a, dict):
            a["title"] = scrub_title(a.get("title"))
            if isinstance(a.get("article"), dict):
                a["article"]["title"] = scrub_title(a["article"].get("title"))
    try:
        items = parse_rss(Path(argv[argv.index("--rss-file") + 1]).read_text() if "--rss-file" in argv else get(RSS))
        if "--backfill" in argv:
            for n in range(BACKFILL_PAGES):
                items += parse_listing(get(LISTING.format(n=n)))
        if not items:
            raise ValueError("the topic's feed lists no release: a failed read")
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=scrub_title(str(e)))
        print(f"{SOURCE_ID}: {scrub_title(str(e))}", file=sys.stderr)
        return 1
    errors = []
    for it in items:
        if not TITLE.search(it["title"]):
            continue
        cur = arts.get(it["url"])
        if cur and cur.get("rss_pubdate") == (it["rss_pubdate"] or cur.get("rss_pubdate")) and cur.get("article"):
            continue
        try:
            page = files[it["url"]] if it["url"] in files else get(it["url"])
            art = parse_article(page)
        except (requests.RequestException, ValueError, KeyError) as e:
            errors.append(scrub_title(f"{it['url']}: {e}"))
            continue
        # the title is matched as published (in memory) and saved only after the scrub
        arts[it["url"]] = {"title": scrub_title(it["title"]), "rss_pubdate": it["rss_pubdate"], "article": art,
                           "read_at": at,
                           "municipal": bool(MUNICIPAL.search(art["body"]))}
        if not files:
            save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "url": it["url"], **art}, indent=1).encode(), "json")
    write_json(STATE_PATH, state)
    recs, not_muni = [], []
    for url, a in sorted(arts.items()):
        if not a.get("municipal"):
            not_muni.append(a["title"])
            continue
        recs += records_for(a["article"], url, a["read_at"])
    meta = {"registry_ids": [SOURCE_ID], "url": RSS, "releases_kept": len(arts) - len(not_muni),
            "not_municipal": not_muni, "errors": errors[:10],
            "cadence": "the topic's RSS each run; --backfill reads the topic's four listing pages once"}
    if errors:
        # an unread release is read again next run (it is not in the state); the feed is not healthy until it is
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error="; ".join(errors[:3]), meta=meta)
    else:
        path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(arts)} wastewater releases known ({len(not_muni)} not municipal); {len(recs)} records "
          f"-> {path}" + (f"; {len(errors)} errors" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
