"""Anne Arundel County Department of Health closings and advisories -> data/build/events/md-aa-health-closings.json

Source
  https://www.aahealth.org/environmental-health/recreational-water-quality/closings-and-advisories
  A Drupal list (?page=0, 1, ...; about 20 notices a page, newest first, each with the page's own date)
  of notice pages. The Department closes a stretch of water "when a sewage spill, leak or other problem
  indicates human waste has impacted the water" (usually for a week) and issues beach advisories for
  high enterococci. Notices are edited in place: a dated update paragraph ("Effective June 9, 2026,
  the Department of Health has rescinded this advisory.") is added above the original, and the title
  gains "*Update 6-9-26*" (the page path can change with it; the Drupal node id does not). No
  licence stated; credit "Anne Arundel County Department of Health".

Record rules
  - Only sewage-related notices are taken (title or text names sewage, sewer, wastewater, effluent,
    a spill or an overflow); the routine high-bacteria beach advisories are left out (meta counts them).
  - A notice page is split into its dated paragraphs ("Severna Park, MD (June 2, 2026) - ..."). The
    oldest one is the notice as issued: one record, source_record_id node-<nid>, event_type
    beach_closure (an emergency closing / closure) or beach_advisory (an advisory or warning), status
    advisory_active, started_at and published_at = that paragraph's date (time_precision day).
  - ended_at holds the notice's own end ("valid until"; raw._valid_until and its basis): the date in
    "in effect until February 16, 2026", or "for one week" / "7 days" counted from the spill date when
    the notice gives it, else from the notice date. With no end stated, ended_at is null.
  - Each later dated paragraph is an update record (node-<nid>:<date>-<kind>) whose parent_event_id is
    the record before it: a rescission or lifting -> advisory_lifted with ended_at = its "Effective"
    date (or the paragraph's date); "remains in effect" / "reinstated" -> advisory_active with the new
    end. The page's own dates are used throughout, never the fetch time; a rescission dated before the
    notice it rescinds (a typed year) falls back to the date in the title's "*Update M-D-YY*" and says so.
  - waterbody_text is the affected stretch as written ("Cypress Creek in Severna Park to the headwaters
    of the Magothy River"); water slugs come from it by name within Maryland and Anne Arundel County
    (ingest/md_waters.py). advice_text is the notice's own advice sentences. The spill's volume and
    time stay in raw (the MDE table carries the discharge itself).
  - source_updated_at is the newest date on the page (its latest update paragraph or the title's
    update date); raw.list_date is the list's date for the page.

Cadence: every 6 hours (closures are posted within about a day of a spill). Notice pages are re-read
when their list entry changes, when they are less than 120 days old, or after 7 days.
Run from pipeline/:  python -m ingest.md_aa_health_closings
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (BUILD_DIR, HEADERS, ROOT, event, now_iso, path_notes_to_meta, read_json, save_raw,
                    scrub_text, write_events, write_json)
from ingest import md_waters

SOURCE_ID = "md-aa-health-closings"
BASE = "https://www.aahealth.org"
LIST_PATH = "/environmental-health/recreational-water-quality/closings-and-advisories"
LIST_URL = BASE + LIST_PATH
STATE_FILE = BUILD_DIR / "md-aa-health-closings-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Anne Arundel County Department of Health"
MAX_PAGES = 15
REFRESH_DAYS = 120
STALE_DAYS = 7
BACTERIA_TITLE = re.compile(r"enterococci or bacteria levels", re.I)
SEWAGE = re.compile(r"\b(sewage|sewer|sanitary|wastewater|effluent|septic|spill|overflow)\b", re.I)
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_TXT = rf"(?:(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"
DATELINE = re.compile(
    r"^\s*(?:\*?\s*update\s*\*?\s*[-:–—]?\s*)?(?P<place>[A-Z][A-Za-z .'’]{1,40}?)\s*,?\s*"
    r"(?:MD|Md\.|Maryland)?\s*,?\s*\((?P<date>[^)]{4,30})\)\s*[-–—:]+\s*", re.I)
TITLE_UPDATE = re.compile(r"\*\s*update\s*[-–:]?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\s*\*", re.I)
LIFT = re.compile(r"\b(rescinded|lifted|has been removed|may now be removed|no longer in effect|reopened)\b", re.I)
REINSTATED = re.compile(r"\breinstated\b", re.I)
CONTINUES = re.compile(r"\b(remains? in effect|will remain in effect|additional overflow)\b", re.I)
ISSUING = re.compile(
    r"(?:issued|ordered|reinstated)\s+(?:an?\s+)?(?P<what>(?:emergency\s+)?(?:closing|closure)|public health advisory|"
    r"health advisory|advisory|warning)\b[^.]{0,60}?\b(?:for|in)\s+(?P<w>.+?)(?:\s+due to\b|\s+in response to\b|"
    r"\s+because\b|\.(?:\s|$)|$)", re.I)
STRETCH_ALT = [
    re.compile(r"\bthe affected area (?:from\s+)?(?P<w>[^.]+?)\s+is closed\b", re.I),
    re.compile(r"\b(?:emergency closing|closure|advisory|warning)\s+for\s+(?P<w>[^.]+?)\s+(?:remains|has been|is|will)\b", re.I),
]
TITLE_STRETCH = re.compile(r"\b(?:for|in)\s+(?P<w>.+?)(?:\s+due to\b|$)", re.I)
UNTIL = re.compile(rf"\buntil\s+(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?(?P<d>{DATE_TXT})", re.I)
WEEK = re.compile(r"\b(?:in effect|reinstated|water contact)\s+for\s+(?:the next\s+)?(?:(?P<n>\d+|one|seven)\s*(?:\(\w+\)\s*)?(?P<u>weeks?|days?))"
                  r"(?P<follow>\s+following\s+(?:the|a)\s+spill)?", re.I)
EFFECTIVE = re.compile(rf"\beffective\s+(?P<d>{DATE_TXT})", re.I)
SPILL_AT = re.compile(rf"\b(?:spill|overflow)\s+occurred\s+(?:overnight\s+)?on\s+(?P<d>{DATE_TXT})"
                      r"(?:,?\s+at\s+(?P<t>\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?))?", re.I)
VOLUME = re.compile(r"(?P<q>(?:over|more than|in excess of|approximately|about|nearly|estimated at)\s+)?"
                    r"(?P<n>\d[\d,.]*)\s*(?P<m>million\s+)?gallons?", re.I)
ADVICE = re.compile(r"\b(advis\w*\s+against|closed\s+(?:for|to)|advisory against|warns against|are advised|"
                    r"should be cautious|consider wearing gloves|wash (?:well|thoroughly|your hands)|clothing should|"
                    r"in effect (?:until|for)|remain in effect)\b", re.I)
NUM_WORDS = {"one": 1, "seven": 7}


# ---------------------------------------------------------------- parsing

def text_of(fragment: str) -> str:
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    t = re.sub(r"<(br|hr)\b[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|div|h\d|li|tr)>", "\n", t, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in t.splitlines() if line.strip())


def parse_list(html: str) -> list[dict]:
    """[{href, title, list_date}] from one list page."""
    out = []
    for m in re.finditer(r'<div class="views-row">(.*?)(?=<div class="views-row">|<nav|</main>|$)', html, re.S):
        block = m.group(1)
        a = re.search(rf'<a href="({re.escape(LIST_PATH)}/[^"#?]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        t = re.search(r'<time datetime="([^"]+)"', block)
        out.append({"href": a.group(1), "title": text_of(a.group(2)).replace("\n", " "),
                    "list_date": t.group(1) if t else None})
    return out


def parse_date(s: str | None) -> date | None:
    s = re.sub(r"\s+", " ", (s or "").strip().replace(".", "")).strip(" ,")
    s = re.sub(r"^(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+", "", s, flags=re.I)
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    if s.lower().startswith("sept"):
        return parse_date("Sep" + s[4:])
    return None


def parse_notice(html: str) -> dict:
    """{nid, title, canonical, paragraphs}."""
    nid = re.search(r'<link rel="shortlink" href="[^"]*/node/(\d+)"', html)
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    i = html.find('id="block-anne-arundel-content"')
    body = html[i:] if i >= 0 else html
    a0, a1 = body.find("<article"), body.find("</article>")
    if a0 >= 0 and a1 > a0:
        body = body[a0:a1]
    return {"nid": nid.group(1) if nid else None, "canonical": canon.group(1) if canon else None,
            "title": text_of(h1.group(1)).replace("\n", " ") if h1 else None,
            "paragraphs": [p for p in text_of(body).split("\n") if p.strip()]}


def sections(paragraphs: list[str]) -> list[dict]:
    """Dated paragraphs, oldest first: [{date, place, text}] (undated paragraphs join the one above)."""
    out: list[dict] = []
    for p in paragraphs:
        m = DATELINE.match(p)
        d = parse_date(m.group("date")) if m else None
        if m and d:
            out.append({"date": d, "place": m.group("place").strip(), "text": p[m.end():].strip(),
                        "dateline": p[:m.end()].strip()})
        elif out:
            out[-1]["text"] += "\n" + p
        else:
            out.append({"date": None, "place": None, "text": p, "dateline": None})
    out = [s for s in out if s["date"] is not None or s["text"].strip()]
    return list(reversed(out))


def title_update_date(title: str | None) -> date | None:
    m = TITLE_UPDATE.search(title or "")
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    yr = yr + 2000 if yr < 100 else yr
    try:
        return date(yr, mo, dy)
    except ValueError:
        return None


def stretch_of(text: str, title: str | None) -> str | None:
    one = " ".join(text.split())
    m = ISSUING.search(one)
    w = m.group("w").strip(" ,;") if m else None
    if w and re.match(r"(?i)an?\s+.*\b(sewage|sewer|overflow|spill)\b", w):
        w = None
    if not w:
        for rx in STRETCH_ALT:
            m2 = rx.search(one)
            if m2:
                w = m2.group("w").strip(" ,;")
                break
    if not w and title:
        t = TITLE_UPDATE.sub("", title)
        m3 = TITLE_STRETCH.search(t)
        w = m3.group("w").strip(" ,;") if m3 else None
    return w or None


def kind_of(text: str) -> str:
    one = " ".join(text.split())
    m = ISSUING.search(one)
    what = (m.group("what") if m else "") or ""
    if re.search(r"clos", what, re.I) or (not what and re.search(r"emergency clos|\bclosure\b", one, re.I)):
        return "beach_closure"
    return "beach_advisory"


def advice_of(text: str) -> str | None:
    one = " ".join(text.split())
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", one)
    keep = [s for s in sents if ADVICE.search(s) and not re.search(r"\b(call|visit|sign up|subscribe)\b", s, re.I)]
    return scrub_text(" ".join(keep)) if keep else None


def spill_of(text: str) -> dict:
    out = {}
    m = SPILL_AT.search(" ".join(text.split()))
    if m:
        d = parse_date(m.group("d"))
        if d:
            out["date"] = d.isoformat()
            if m.group("t"):
                tt = re.sub(r"[.\s]", "", m.group("t")).upper()
                try:
                    t = datetime.strptime(tt, "%I:%M%p").time()
                    out["at"] = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=TZ).isoformat()
                except ValueError:
                    pass
    v = VOLUME.search(" ".join(text.split()))
    if v:
        out["volume_text"] = v.group(0)
    return out


def valid_until(text: str, issued: date | None, spill_date: date | None) -> tuple[date | None, str | None]:
    one = " ".join(text.split())
    m = UNTIL.search(one)
    if m:
        d = parse_date(m.group("d"))
        if d:
            return d, f"the notice: {m.group(0)!r}"
    m = WEEK.search(one)
    if m:
        n = m.group("n").lower()
        n = NUM_WORDS.get(n, None) if not n.isdigit() else int(n)
        if n:
            days = n * 7 if m.group("u").lower().startswith("week") else n
            if m.group("follow") and spill_date:
                return spill_date + timedelta(days=days), f"the notice: {m.group(0)!r}, counted from the spill date"
            if issued:
                how = "counted from the notice date" + (" (the spill date is not given)" if m.group("follow") else "")
                return issued + timedelta(days=days), f"the notice: {m.group(0)!r}, {how}"
    return None, None


def at_day(d: date | None) -> str | None:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat() if d else None


# ---------------------------------------------------------------- records

def is_sewage(title: str | None, paragraphs: list[str]) -> bool:
    t = " ".join([title or ""] + paragraphs)
    return bool(SEWAGE.search(t))


def records_for(notice: dict, item: dict, fetched_at: str) -> tuple[list[dict], list[str]]:
    """The issued record and its update records for one sewage notice page."""
    nid = notice.get("nid")
    url = notice.get("canonical") or (BASE + item["href"])
    secs = sections(notice["paragraphs"])
    if not secs:
        return [], ["no dated paragraph"]
    problems = []
    title = notice.get("title") or item.get("title")
    t_upd = title_update_date(title)
    first = secs[0]
    issued = first["date"]
    if issued is None:
        problems.append("the oldest paragraph has no readable date")
    spill = spill_of(first["text"])
    spill_date = date.fromisoformat(spill["date"]) if spill.get("date") else None
    until, until_basis = valid_until(first["text"], issued, spill_date)
    stretch = stretch_of(first["text"], title)
    slugs, notes = md_waters.match_waters(stretch, None, None, "Anne Arundel") if stretch else ([], [])
    etype = kind_of(first["text"])
    dates = [s["date"] for s in secs if s["date"]] + ([t_upd] if t_upd else [])
    newest = max(dates) if dates else None
    page = {"nid": nid, "url": url, "title": title, "list_date": item.get("list_date"),
            "title_update_date": t_upd.isoformat() if t_upd else None,
            "sections": [{"date": s["date"].isoformat() if s["date"] else None, "dateline": s["dateline"]} for s in secs]}
    common = dict(source_id=SOURCE_ID, fetched_at=fetched_at, source_url=url, event_type=etype,
                  authority=AUTHORITY, waterbody_text=stretch, water_slugs=slugs,
                  water_match="name" if slugs else "none", time_precision="day",
                  source_updated_at=at_day(newest))
    water_note = {"stretch": stretch, "name_notes": notes} if notes else {"stretch": stretch}
    raw0 = {"page": page, "section": {"date": issued.isoformat() if issued else None, "dateline": first["dateline"],
                                      "text": first["text"]},
            "_water": water_note, "_spill": spill or None,
            "_valid_until": until.isoformat() if until else None, "_valid_until_basis": until_basis}
    rid0 = f"node-{nid}" if nid else "path-" + item["href"].rsplit("/", 1)[-1]
    recs = [event(**common, source_record_id=rid0, status="advisory_active",
                  started_at=at_day(issued), ended_at=at_day(until), published_at=at_day(issued),
                  advice_text=advice_of(first["text"]), raw=raw0,
                  parse_error="; ".join(problems) or None)]
    parent, start, used = recs[0]["event_id"], issued, Counter()
    for s in secs[1:]:
        text, d = s["text"], s["date"]
        prob = []
        eff = EFFECTIVE.search(" ".join(text.split()))
        eff_d = parse_date(eff.group("d")) if eff else None
        if LIFT.search(text):
            kind = "lifted"
        elif REINSTATED.search(text):
            kind = "reinstated"
        elif CONTINUES.search(text):
            kind = "extended"
        else:
            kind = "update"
        when = eff_d or d
        if when and start and when < start:
            if t_upd and t_upd >= start:
                prob.append(f"dated {when.isoformat()}, before the notice it updates ({start.isoformat()}); "
                            f"the title's update date {t_upd.isoformat()} used")
                when = t_upd
                d = d if d and d >= start else t_upd
            else:
                prob.append(f"dated {when.isoformat()}, before the notice it updates ({start.isoformat()})")
        rid = f"{rid0}:{(d or when).strftime('%Y%m%d') if (d or when) else 'nodate'}-{kind}"
        used[rid] += 1
        if used[rid] > 1:
            rid += f"-{used[rid]}"
        raw = {"page": {"nid": nid, "url": url}, "section": {"date": d.isoformat() if d else None,
                                                            "dateline": s["dateline"], "text": text},
               "_update_kind": kind}
        if kind == "lifted":
            rec = event(**common, source_record_id=rid, parent_event_id=parent, status="advisory_lifted",
                        started_at=at_day(start), ended_at=at_day(when), published_at=at_day(d),
                        advice_text=None, raw=raw, parse_error="; ".join(prob) or None)
        else:
            new_start = d if kind == "reinstated" and d else start
            u, ub = valid_until(text, d, None)
            raw["_valid_until"], raw["_valid_until_basis"] = (u.isoformat() if u else None), ub
            rec = event(**common, source_record_id=rid, parent_event_id=parent, status="advisory_active",
                        started_at=at_day(new_start), ended_at=at_day(u), published_at=at_day(d),
                        advice_text=advice_of(text), raw=raw, parse_error="; ".join(prob) or None)
            start = new_start
        recs.append(rec)
        parent = rec["event_id"]
    return recs, problems


# ---------------------------------------------------------------- fetch and main

def get(sess: requests.Session, url: str) -> str:
    r = sess.get(url, timeout=(15, 60))
    r.raise_for_status()
    return r.text


def fetch_list(sess: requests.Session) -> list[dict]:
    items, seen = [], set()
    for page in range(MAX_PAGES):
        got = parse_list(get(sess, f"{LIST_URL}?page={page}"))
        new = [x for x in got if x["href"] not in seen]
        if not new:
            break
        for x in new:
            seen.add(x["href"])
            items.append({**x, "list_page": page})
        time.sleep(0.3)
    return items


def needs_fetch(item: dict, cached: dict | None, now: datetime) -> bool:
    if not cached or not cached.get("html"):
        return True
    if cached.get("list_date") != item.get("list_date") or cached.get("title") != item.get("title"):
        return True
    try:
        fetched = datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
        listed = datetime.fromisoformat(item["list_date"]).replace(tzinfo=TZ) if item.get("list_date") else None
    except (KeyError, ValueError, TypeError):
        return True
    if listed is not None and now - listed < timedelta(days=REFRESH_DAYS):
        return True
    return now - fetched > timedelta(days=STALE_DAYS)


def build(items: list[dict], pages: dict, fetched_at: str) -> tuple[list[dict], dict]:
    records, stats = [], Counter()
    for item in items:
        if BACTERIA_TITLE.search(item.get("title") or ""):
            stats["bacteria_advisories_skipped"] += 1
            continue
        html = (pages.get(item["href"]) or {}).get("html")
        if not html:
            stats["notice_page_missing"] += 1
            continue
        notice = parse_notice(html)
        if not is_sewage(notice.get("title") or item.get("title"), notice["paragraphs"]):
            stats["not_sewage_skipped"] += 1
            continue
        recs, probs = records_for(notice, item, (pages.get(item["href"]) or {}).get("fetched_at") or fetched_at)
        if probs:
            stats["notices_with_problems"] += 1
        stats["sewage_notices"] += 1
        records += recs
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    out = dict(stats)
    out["records"] = len(records)
    out["by_status"] = dict(Counter(r["status"] for r in records))
    out["by_type"] = dict(Counter(r["event_type"] for r in records))
    out["water_match"] = dict(Counter(r["water_match"] for r in records if not r.get("parent_event_id")))
    return records, out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refetch", action="store_true", help="read every notice page again")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    now = datetime.now(UTC)
    state = read_json(STATE_FILE, {}) or {}
    cache = state.get("pages") or {}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        items = fetch_list(sess)
        if not items:
            raise ValueError("the closings list has no entries (layout changed?)")
        fetched = 0
        for item in items:
            if BACTERIA_TITLE.search(item.get("title") or ""):
                continue
            c = cache.get(item["href"])
            if args.refetch or needs_fetch(item, c, now):
                html = get(sess, BASE + item["href"])
                cache[item["href"]] = {"html": html, "fetched_at": now_iso(), "list_date": item.get("list_date"),
                                       "title": item.get("title")}
                fetched += 1
                time.sleep(0.3)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1

    # keep the list and every notice page read (raw HTML) whenever their text changed
    hrefs = {i["href"] for i in items}
    pages = {h: c for h, c in cache.items() if h in hrefs}
    texts = {h: parse_notice(c["html"])["paragraphs"] for h, c in pages.items() if c.get("html")}
    sha = hashlib.sha256(json.dumps({"list": items, "notices": texts}, sort_keys=True).encode()).hexdigest()
    raw_path = state.get("raw_path")
    if sha != state.get("sha256"):
        bundle = {"list_url": LIST_URL, "fetched_at": fetched_at, "list": items,
                  "notices": {h: {"fetched_at": c.get("fetched_at"), "html": c.get("html")} for h, c in pages.items()}}
        raw_path = str(save_raw(SOURCE_ID, json.dumps(bundle, ensure_ascii=False), "json").relative_to(ROOT))
    write_json(STATE_FILE, {"sha256": sha, "raw_path": raw_path, "fetched_at": fetched_at, "pages": pages})

    records, stats = build(items, cache, fetched_at)
    records = redact.redact_events(records)      # private individuals' names in quoted text (build/redact.py)
    meta = {**stats, "list_url": LIST_URL, "list_entries": len(items), "notice_pages_read_this_run": fetched,
            "raw_path": raw_path, "credit": "Anne Arundel County Department of Health, Closings and Advisories",
            "registry_ids": ["md-aahealth-closings-advisories"]}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {len(items)} list entries, {stats.get('sewage_notices', 0)} sewage notices -> "
          f"{len(records)} records {stats['by_status']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
