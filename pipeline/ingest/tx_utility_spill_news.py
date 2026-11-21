"""Austin Water and El Paso Water spill news releases: the releases the two utilities post when a wastewater spill is
large enough for the notice Texas law requires (sources tx-austin-water-spill-news, tx-el-paso-water-spill-news).

Sources
  Austin Water: https://www.austintexas.gov/water/news (HTML list, about ten items a page, ?page=N from 0, newest
    first; each item a title linking /water/news/<slug>). The release page gives "Release Date: <Month D, YYYY>" (no
    time) and the text. Read 2026-11-17: six list pages, five spill releases (December 2024 to September 2026).
  El Paso Water: https://www.epwater.org/about-us/newsroom (HTML list, the newest 25; ?show=all lists every release
    since 2019); each item a title linking /about-us/newsroom/<slug>. The release page gives "Published on <Month D,
    YYYY>". Read 2026-11-17: 189 releases, nine about a wastewater spill or overflow (2020 to 2026).
  Neither site has a feed. The hourly run reads the first list page of each; `--backfill` reads the whole archive.

Record rules (rules only; the text of a release is read in memory and never stored)
  - A release is a notice when its title names a sewer overflow, a wastewater or sewage spill, overflow or line break.
    A title with "update" is a follow-up of an earlier release (counted apart in meta.not_notices).
  - One record per release (source_record_id the release's slug). Times are local: Central for Austin, Mountain for
    El Paso (America/Denver). The spill's day is the first date the text gives in a sentence about the spill (a date
    without a year takes the release's year, the year before when that would fall after it); "On Monday morning"
    without a date is the most recent Monday on or before the release. A clock time in that sentence, or in the first
    sentence that says when the spill was discovered or reported, makes it minute precision; "discovered" or
    "reported" marks raw.start_is_upper_bound (the spill began at or before it). No day in the text: the release's day,
    day precision, upper bound. An end only where the text says the overflow was stopped at a clock time with no other
    date in that sentence, on the start's day and after its start time; otherwise none (never invented).
  - Volume: the one gallons figure the text gives ("Approximately 115,000 gallons" estimated); a bound ("More than
    100,000 gallons", "over 100,000 gallons") keeps only its words; several different figures keep the words only.
  - Water: a named creek, river or the Rio Grande in a sentence that says the wastewater flowed, spilled, reached,
    emptied or was released into it ("a tributary of Gilliland Creek" names Gilliland Creek); a water the text says the
    spill did not reach is left out. A release naming none (a storm drain, a pond, a dry creek bed, the plant's
    property) is listed with its city and county, unplaced (raw._placement named_water_only; no geocoding).
    raw.reached_water False where the text says the spill was contained on property or reached no waterway.
  - advice_text: the release's own sentence telling the public to avoid contact or keep away, quoted; neither utility
    gives a window, so the site's caution applies by the existing rules. Statements that water "remains safe" or poses
    "no risk" are never kept.
  - One spill, one record: a release whose operator, start day (within a day) and volume meet a row of TCEQ's open
    data gets duplicate_of that row (ingest/tx_spill_notice_form.link_tceq), recomputed every run.

Privacy: releases name staff (quoted officials, a division manager with a telephone number) and a media line: none is
read into a record. The location comes from the title with house numbers dropped; the text's street addresses are not
kept. data/raw keeps the parsed list items only (title, slug, date).

Failures: a list page that cannot be read, or that lists no release, writes ok=False for that utility and keeps its
earlier records; a list read with no spill release is a healthy run. A release page that cannot be read is tried on the
next run (meta.unread).

Run from pipeline/:  python -m ingest.tx_utility_spill_news [--site austin|elpaso] [--backfill] [--dir saved/]
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from common import error_detail
from ingest import tx_spill_notice_form as F

SITES = {
    "austin": {
        "source_id": "tx-austin-water-spill-news", "base": "https://www.austintexas.gov",
        "list": "https://www.austintexas.gov/water/news", "path": "/water/news/",
        "tz": F.CENTRAL, "tz_name": "America/Chicago", "county": "Travis", "city": "Austin",
        "discharger_id": "tx-city-of-austin", "discharger": "City of Austin (Austin Water)",
        "operator_ids": ["tx-city-of-austin"], "permit_prefix": None,
        "authority": "Austin Water (City of Austin), news release",
        "date_re": r"Release\s+Date:\s*(" + F.MONTH_RE + r"\s+\d{1,2},?\s+\d{4})",
        "body_start": r"For\s+Immediate\s+Release", "body_end": r"Share\s+this|<footer|Austin\s+Water\s+provides\s+safe",
    },
    "elpaso": {
        "source_id": "tx-el-paso-water-spill-news", "base": "https://www.epwater.org",
        "list": "https://www.epwater.org/about-us/newsroom", "path": "/about-us/newsroom/",
        "tz": F.MOUNTAIN, "tz_name": "America/Denver", "county": "El Paso", "city": "El Paso",
        "discharger_id": "tx-el-paso-water-utilities-public-service-board",
        "discharger": "El Paso Water Utilities Public Service Board (El Paso Water)",
        "operator_ids": ["tx-el-paso-water-utilities-public-service-board", "tx-rn101434645", "tx-rn104403209",
                         "tx-rn105052468"], "permit_prefix": None,
        "authority": "El Paso Water, news release",
        "date_re": r"Published\s+on\s+(" + F.MONTH_RE + r"\s+\d{1,2},?\s+\d{4})",
        "body_start": r"Published\s+on", "body_end": r"<footer|Related\s+News|newsletter-signup",
    },
}
LIVE_PAGES = 1
PAUSE_S = 0.5

NOTICE_TITLE = re.compile(r"sewer\s+overflow|wastewater\s+(?:sludge\s+)?(?:spill|overflow|line\s+break)|sewage\s+spill|"
                          r"\bspill\s+contained|\bsewer\s+spill", re.I)
UPDATE_TITLE = re.compile(r"\bupdate\b", re.I)
SPILL = re.compile(r"\b(?:overflow(?:ed|s)?|spill(?:ed|s)?|leak(?:ing|ed)?|break|discharge[ds]?)\b", re.I)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY = re.compile(r"\b(?:on\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.I)
FOUND = re.compile(r"\b(?:discovered|reported|first\s+reported|respond(?:ed|ing|s)?)\b", re.I)
ENTRY = re.compile(r"\b(?:into|reach(?:ed|es)?|flow(?:ed|s)?|empt(?:ies|ied)|released\s+to|made\s+its\s+way|spilled\s+(?:in)?to)\b",
                   re.I)
NOT_REACHED = re.compile(r"did\s+not\s+reach\s+((?:[A-Z][\w'’-]*\s+){1,3}(?:Creek|River)|the\s+Rio\s+Grande|Rio\s+Grande)", re.I)
NO_WATER = re.compile(r"\bno\s+storm\s+drains?,\s+waterways|contain(?:ed)?\s+the\s+spill\s+within\s+the\s+[\w\s]{0,30}property|"
                      r"spilled\s+within\s+the\s+[\w\s]{0,30}property", re.I)
ADVICE = re.compile(r"\b(?:avoid\s+contact|keep\s+(?:livestock|pets|children)[^.]{0,40}away|stay\s+(?:out|away))\b", re.I)
REASSURE = re.compile(r"\bsafe\b|\bclean\b|\bsaid\b|\bsays\b|\bdiluted\b|\bno\s+(?:immediate\s+)?risk|not\s+at\s+risk|no\s+impact", re.I)
STOPPED = re.compile(r"\bstopped(?:\s+the\s+(?:overflow|spill|flow|leak))?\s+at\s+(?:about\s+|approximately\s+)?(\d{1,2})(?::(\d{2}))?\s*"
                     r"([ap])\.?\s*m\b", re.I)
WATER = re.compile(r"\b((?:[A-Z][\w'’-]*\s+){1,3}(?:Creek|River))\b" + F.NOT_AFTER_WATER + r"|\b(Rio\s+Grande)\b" +
                   F.NOT_AFTER_WATER)
NEGATED_ENTRY = re.compile(r"\b(?:did\s+not|didn.t|never|not)\s+(?:flow|reach|enter|spill|make\s+its\s+way|get)\b|"
                           r"\bno\s+(?:waste\s*water|sewage)\s+(?:reached|entered|flowed)", re.I)


def _words(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def list_items(page: str, site: dict) -> list[dict]:
    """[{title, url, slug}] of a list page: each anchor to a release with its text as the title (first seen wins)."""
    out, seen = [], set()
    for m in re.finditer(r"<a\s[^>]*href=\"((?:" + re.escape(site["base"]) + r")?" + re.escape(site["path"]) +
                         r"[a-z0-9-]+)\"[^>]*>(.*?)</a>", page, re.S | re.I):
        title = _words(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))))
        if not title or re.fullmatch(r"(?i)continue reading|read more", title):
            t = re.search(r'\btitle="([^"]+)"', m.group(0))
            title = _words(html.unescape(t.group(1))) if t else ""
        url = urljoin(site["base"], m.group(1))
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if not title or slug in seen or slug in ("newsletter-signup",):
            continue
        seen.add(slug)
        out.append({"title": title, "url": url, "slug": slug})
    return out


def release(page: str, site: dict) -> tuple[date | None, str]:
    """(the release date, the release's text) from a release page."""
    m = re.search(site["date_re"], _words(html.unescape(re.sub(r"<[^>]+>", " ", page))), re.I)
    pub = None
    if m:
        try:
            pub = datetime.strptime(re.sub(r"\s+", " ", m.group(1).replace(",", "")), "%B %d %Y").date()
        except ValueError:
            pub = None
    s = re.search(site["body_start"], page, re.I)
    body = page[s.start():] if s else page
    e = re.search(site["body_end"], body[20:], re.I)
    body = body[:e.start() + 20] if e else body
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"</(?:p|li|div|h\d)>|<br\s*/?>", ". ", body, flags=re.I)
    return pub, _words(html.unescape(re.sub(r"<[^>]+>", " ", body)))


def sentences(text: str) -> list[str]:
    t = re.sub(r"\b([ap])\.m\.", r"\1m", text)
    t = re.sub(r"\b(St|Dr|Ave|Mr|Ms|Mrs|U\.S|Rd|Blvd|No|Jan|Feb|Mar|Apr|Aug|Sept|Sep|Oct|Nov|Dec)\.", r"\1", t)
    return [x.strip(" .") for x in re.split(r"(?<!\b[A-Z]\.)(?<=[.!?])\s+", t) if x.strip(" .")]


def _clock(h, mi, ap) -> tuple[int, int]:
    return int(h) % 12 + (12 if ap.lower() == "p" else 0), int(mi or 0)


def spill_times(ss: list[str], pub: date, tz) -> dict:
    out = {"start": None, "precision": None, "kind": None, "end": None, "words": None}
    day, si = None, None
    for i, s in enumerate(ss):
        if not SPILL.search(s) and not FOUND.search(s):
            continue
        d = F.DATE_WORDS.search(s)
        if d:
            day = F.spill_time(d.group(0), tz, pub)[0]
            if day:
                day, si = date.fromisoformat(day[:10]), i
                break
        w = WEEKDAY.search(s)
        if w and SPILL.search(s):
            wd = WEEKDAYS.index(w.group(1).lower())
            day, si = pub - timedelta(days=(pub.weekday() - wd) % 7), i
            break
    if day is None:
        return out
    def other_day(x: str) -> bool:
        """Whether the sentence gives a day other than the spill's (its clock belongs to that day)."""
        for dm in F.DATE_WORDS.finditer(x):
            got = F.spill_time(dm.group(0), tz, pub)[0]
            if got and date.fromisoformat(got[:10]) != day:
                return True
        for wm in WEEKDAY.finditer(x):
            if WEEKDAYS.index(wm.group(1).lower()) != day.weekday():
                return True
        return bool(re.search(r"\b(?:next|following)\s+(?:day|morning|afternoon|evening)\b", x, re.I))

    s = ss[si]
    cand = [s] + [x for x in ss[si + 1:si + 10] if FOUND.search(x) or re.search(r"\boccurred\b", x, re.I)]
    for x in cand:
        c = F.CLOCK.search(x)
        if c and not STOPPED.search(x[:c.end() + 1]) and (x is s or not other_day(x)):
            h, mi = F._clock(c)
            out.update(start=datetime(day.year, day.month, day.day, h, mi, tzinfo=tz).isoformat(), precision="minute",
                       words=_words(x)[:160])
            out["kind"] = "found" if FOUND.search(x) and not re.search(r"\boccurred\b", x, re.I) else "start"
            break
    else:
        out.update(start=day.isoformat(), precision="day", words=_words(s)[:160],
                   kind="found" if FOUND.search(s) and not re.search(r"\boccurred\b", s, re.I) else "start")
    if out["precision"] == "minute":
        for x in ss[si:si + 10]:
            m = STOPPED.search(x)
            if m and not other_day(x):
                h, mi = _clock(*m.groups())
                end = datetime(day.year, day.month, day.day, h, mi, tzinfo=tz)
                if end.isoformat() > out["start"]:
                    out["end"] = end.isoformat()
                break
    return out


def volume_of(text: str) -> tuple[int | None, str, str | None]:
    found = [m for m in F.VOLUME.finditer(text)]
    figures = {m.group(2) for m in found}
    if not found:
        return None, "unknown", None
    if len(figures) > 1:
        return None, "estimated", "; ".join(dict.fromkeys(_words(m.group(0)) for m in found))
    return F.volume(_words(found[0].group(0)) if not re.search(r"approx|estimat", text[max(0, found[0].start() - 20):found[0].start()], re.I)
                    else _words(text[max(0, found[0].start() - 20):found[0].end()]))


def waters_of(ss: list[str]) -> tuple[list[str], bool | None]:
    text = " ".join(ss)
    excluded = {re.sub(r"^the\s+", "", _words(m.group(1)), flags=re.I).lower() for m in NOT_REACHED.finditer(text)}
    out = []
    for s in ss:
        if not ENTRY.search(s) or NEGATED_ENTRY.search(s):
            continue
        for m in WATER.finditer(s):
            name = _words(m.group(1) or m.group(2))
            name = re.sub(r"^(?:The|Into|And|Of|A)\s+", "", name)
            if name.lower() in excluded or F.NOT_A_WATER.search(name) or len(name.split()) < 2:
                continue
            if re.search(r"(?:Plant|Station|Facility|Lift)\b", s[m.end():m.end() + 30]) and not ENTRY.search(s[m.end():m.end() + 30]):
                continue
            if name not in out:
                out.append(name)
    if out:
        return out, True
    return out, (False if NO_WATER.search(text) else None)


def advice_of(ss: list[str]) -> str | None:
    for s in ss:
        if ADVICE.search(s) and not REASSURE.search(s):
            s = F.street_place(s) or ""
            return common.scrub_names(common.scrub_text(s if s.endswith(".") else s + "."))
    return None


def place_of(title: str) -> str | None:
    m = re.search(r"\b(?:near|at|in|along)\s+(.+)$", title, re.I)
    if not m:
        return None
    place = re.sub(r"\s+(?:and\s+)?(?:contained|reported\s+to\s+TCEQ)\s*$", "", m.group(1), flags=re.I)
    return F.street_place(place)


def record(item: dict, pub: date, text: str, site: dict, at: str) -> dict:
    ss = sentences(text)
    t = spill_times(ss, pub, site["tz"])
    gal, flag, vtext = volume_of(text)
    ws, reached = waters_of(ss)
    raw = {"state": "TX", "county": site["county"], "city": site["city"], "time_zone": site["tz_name"],
           "_placement": "named_water_only", "provenance": "operator", "title": common.scrub_text(F.street_place(item["title"]) or item["title"]),
           "place_text": place_of(item["title"]), "waters_named": ws, "reached_water": reached,
           "operator_ids": site["operator_ids"], "state_permit_prefix": site["permit_prefix"],
           "legal_basis": "30 TAC 319.302-319.303 (notice to local officials and the media within 24 hours)"}
    if t["start"]:
        raw["start_kind"] = t["kind"]
        raw["start_is_upper_bound"] = t["kind"] == "found"
        raw["start_basis"] = ("the time the release says the spill was discovered or reported; it began at or before it"
                              if t["kind"] == "found" else "the day and time the release gives for the spill")
        started, precision = t["start"], t["precision"]
    else:
        started, precision = pub.isoformat(), "day"
        raw["start_is_upper_bound"] = True
        raw["start_basis"] = "the release's day: the text gives no day for the spill; it began on or before it"
    if t["end"]:
        raw["end_basis"] = "the time the release says the overflow was stopped"
    material = "wastewater sludge" if re.search(r"sludge", item["title"], re.I) else "wastewater"
    return event(
        source_id=site["source_id"], source_record_id=item["slug"], event_type="sso",
        status="ended" if t["end"] else "unknown",
        discharger_id=site["discharger_id"], discharger_name=site["discharger"], outfall_name=raw["place_text"],
        waterbody_text="; ".join(ws) if ws else None, started_at=started, ended_at=t["end"], time_precision=precision,
        published_at=pub.isoformat(), fetched_at=at, material=material, volume_gal=gal, volume_text=vtext,
        estimate_flag=flag, authority=site["authority"], advice_text=advice_of(ss), source_url=item["url"], raw=raw)


# ---------------------------------------------------------------- fetch and run

def get(url: str, params=None) -> str:
    r = requests.get(url, params=params, headers=HEADERS, timeout=(20, 120))
    r.raise_for_status()
    return r.text


def list_pages(name: str, backfill: bool, src: Path | None) -> list[str]:
    site = SITES[name]
    if src:
        return [p.read_text() for p in sorted(src.glob(f"{name}-list*.html"))]
    if name == "elpaso":
        return [get(site["list"], {"show": "all"} if backfill else None)]
    pages = []
    for n in range(40 if backfill else LIVE_PAGES):
        page = get(site["list"], {"page": n} if n else None)
        if n and not list_items(page, site):
            break
        pages.append(page)
        time.sleep(PAUSE_S if backfill else 0)
    return pages


def run_site(name: str, pages: list[str], prev: list[dict], at: str, get_release,
             retry: list[dict] | None = None) -> tuple[list[dict], dict]:
    """retry: list items whose release could not be read on an earlier run (meta.unread_items), read again even
    after they leave the first list page."""
    site = SITES[name]
    recs = {r["event_id"]: r for r in prev}
    stats = {"items": 0, "notices": 0, "not_notices": {}, "unread": [], "unread_items": []}
    seen = set()
    listed = [it for page in pages for it in list_items(page, site)]
    for it in listed + [r for r in (retry or []) if isinstance(r, dict) and r.get("slug")]:
        if it["slug"] in seen:
            continue
        seen.add(it["slug"])
        stats["items"] += 1
        if not NOTICE_TITLE.search(it["title"]):
            continue
        if UPDATE_TITLE.search(it["title"]):
            stats["not_notices"]["follow-up of an earlier release"] = stats["not_notices"].get("follow-up of an earlier release", 0) + 1
            continue
        stats["notices"] += 1
        eid = f"{site['source_id']}:{it['slug']}"
        if eid in recs:
            recs[eid]["fetched_at"] = at
            continue
        body = get_release(it["url"])
        pub, text = release(body, site) if body is not None else (None, "")
        if pub is None:
            stats["unread"].append(it["url"])
            stats["unread_items"].append({"title": F.street_place(it["title"]), "url": it["url"], "slug": it["slug"]})
            continue
        r = record(it, pub, text, site, at)
        r["raw"]["first_seen_at"] = at
        recs[eid] = r
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    for r in out:      # the operator test of link_tceq: any of the utility's TCEQ entities
        r["raw"]["operator_ids"] = site["operator_ids"]
    stats["duplicates_of_tceq"] = F.link_tceq(out, F.tceq_rows())
    return out, stats


def safe_list(pages: list[str], site: dict) -> str:
    """What data/raw keeps of the list pages: the spill releases only, titles without house numbers."""
    keep = [{"title": F.street_place(it["title"]), "url": it["url"]} for p in pages for it in list_items(p, site)
            if NOTICE_TITLE.search(it["title"])]
    return json.dumps(keep, ensure_ascii=False)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    names = [argv[argv.index("--site") + 1]] if "--site" in argv else list(SITES)
    src = Path(argv[argv.index("--dir") + 1]) if "--dir" in argv else None
    backfill = "--backfill" in argv
    rc = 0
    for name in names:
        site = SITES[name]
        path = common.EVENTS_DIR / f"{site['source_id']}.json"
        prev_doc = read_json(path, {}) or {}
        prev = prev_doc.get("records") or []
        retry = (prev_doc.get("meta") or {}).get("unread_items") or []

        def get_release(url, name=name):
            if src:
                p = src / f"{name}-{url.rstrip('/').rsplit('/', 1)[-1]}.html"
                return p.read_text() if p.exists() else None
            try:
                time.sleep(PAUSE_S)
                return get(url)
            except requests.RequestException as e:
                print(f"{site['source_id']}: release not read ({url}: {type(e).__name__})", file=sys.stderr)
                return None
        try:
            pages = list_pages(name, backfill, src)
            if not pages or not any(list_items(p, site) for p in pages):
                raise ValueError("no release listed on the list page (the layout may have changed)")
            recs, stats = run_site(name, pages, prev, now_iso(), get_release, retry)
        except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as e:
            write_events(site["source_id"], [], ok=False, error=error_detail(e))
            print(f"{site['source_id']}: run not ok ({error_detail(e)})", file=sys.stderr)
            rc = 1
            continue
        if not src:
            save_raw(site["source_id"], safe_list(pages, site).encode(), "json")
        all_unread = bool(stats["unread"]) and len(stats["unread"]) >= stats["notices"]
        out = write_events(site["source_id"], recs, ok=not all_unread, partial=all_unread,
                           error="no spill release could be read" if all_unread else None, meta={
            "registry_ids": [site["source_id"]], "url": site["list"], **stats,
            "credit": site["authority"].replace(", news release", " news releases"),
            "caveat": ("The utility posts releases on large spills (the public-notice threshold of 30 TAC 319.302), not on "
                       "every spill; the times and volumes are its own estimates."),
            "cadence": "every refresh (the first list page); --backfill reads the whole archive"})
        print(f"{site['source_id']}: {len(recs)} records ({stats}) -> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
