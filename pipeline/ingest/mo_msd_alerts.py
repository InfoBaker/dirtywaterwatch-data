"""MSD Project Clear's sewage overflow notices (Metropolitan St. Louis Sewer District, Missouri): the District's own
alerts and news releases about overflows, force main and sewer breaks and discharges, as dated sewage reports.

Source
  https://msdprojectclear.org/newsroom/ (registry: mo-msd-stl-project-clear). The site is WordPress and its REST API
  answers the identified client: https://msdprojectclear.org/wp-json/wp/v2/posts?per_page=100&page=N with only the
  fields read here (id, date, date_gmt, modified_gmt, link, title, content). The hourly run reads the newest 50 posts;
  `--backfill` reads every page (845 posts on 2026-11-14, 9 pages). The District's own posts are under /newsroom/alerts/,
  /newsroom/press-releases/ and /newsroom/post-types/; /newsroom/in-the-news/ (425 posts) and /newsroom/blog/ are press
  coverage and features, never read as notices. Read 2026-11-14: 92 of the District's own posts have an overflow word
  in the title (June 2013 to January 2026); NOT_EVENT drops the oil sheen and basement-backup posts; follow-ups
  ("Repairs ... Completed", "Update", "Cleanup Complete", "Discharge Halted") are kept as copies of the first notice
  (duplicate_of) when one for the same place is within 14 days. The "Sewer Discharge" category holds only 9 of them:
  it is not used as the filter. MSD publishes some overflows, not every one; no rule requiring the posts was found
  (the District's 2011 consent decree with EPA and the State was not read here).

Record rules
  - A post is a notice when its path is one of the District's own and its title names an overflow, a discharge, a
    sewage spill or a force main or sewer main break, and it is not about an oil sheen, a basement backup, a ballot,
    rates or a tunnel project (NOT_EVENT).
  - Times (America/Chicago): the post's own publication time is published_at (date_gmt, UTC). The event day is the
    first date the text gives; a weekday alone ("discovered Tuesday morning", "late Friday night") is the latest such
    day on or before the post's own Central day; "yesterday" the day before it; "today", "this morning" or "earlier
    today" the post's day. A clock time in the same sentence makes the start minute-precision. raw.start_kind says what
    the time marks ("discovered", "reported", "occurred", "started"); a discovery or report time is an upper bound of
    the start (raw.start_is_upper_bound). With no day at all the record is dated to the post's day, raw.start_kind
    "publication" (the overflow happened on or before it). MSD gives no end time: ended_at stays null (cleanup or a
    repair is not an end of the discharge), status unknown.
  - Water: a named creek, river, branch or lake that the text says the wastewater entered, reached, flowed or spilled
    into, or that MSD asks people to avoid; the first is the receiving water, all in raw.waters_named. MSD's own
    avoid-contact sentence is advice_text (its conditional end, "until the cleanup is complete and the warning signs
    are removed", is not a date and is never turned into one). A post that names no water is kept, placed on no water.
  - Volume: "N gallons" as MSD states it, estimated when it says estimated or approximately.
  - Operator: the Metropolitan St. Louis Sewer District (MSD Project Clear); the plant permit is not assigned.
  - Place: no point; raw.counties names MSD's service area (St. Louis County and the City of St. Louis), so a water
    named in the post is placed only on a record of that name that reaches one of them.

Privacy: the posts name contractors and occasionally staff; only the parsed fields and the post text through the
house-number and personal-data scrub are stored; data/raw keeps those fields only, never the response.
Run from pipeline/:  python -m ingest.mo_msd_alerts [--backfill] [--file posts.json ...]
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from common import error_detail
from ingest.mo_kc_water_news import (TIME, clock, find_date, migrate_water_text, safe_link, safe_text, sentences, volume,
                                     water_text, waters)

SOURCE_ID = "mo-msd-stl-project-clear"
API = "https://msdprojectclear.org/wp-json/wp/v2/posts"
HOME = "https://msdprojectclear.org/newsroom/"
TZ = ZoneInfo("America/Chicago")
AUTHORITY = "Metropolitan St. Louis Sewer District (MSD Project Clear), alert or news release"
DISCHARGER_ID = "mo-st-louis-mo0025151"
DISCHARGER = "Metropolitan St. Louis Sewer District"
FIELDS = "id,date,date_gmt,modified_gmt,link,title,content"
OWN_PATH = re.compile(r"/newsroom/(?:alerts|press-releases|post-types)/")
NOTICE = re.compile(r"overflow|force main|sewage|spill|sewer (?:main )?break|main break|discharge|bypass", re.I)
NOT_EVENT = re.compile(r"sheen|basement|backups?\b|ballot|\brates?\b|tunnel|propositions?|\bbonds?\b|incinerator|"
                       r"grant|know your zone|holiday|fog\b|voters?|\bfunds?\b", re.I)
FOLLOW_UP = re.compile(r"\bcomplete[ds]?\b|\bupdate[ds]?\b|\bhalted\b|\bupdated discharge\b", re.I)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
AVOID = re.compile(r"[^.]*\bavoid (?:direct )?contact with\b[^.]*\.", re.I)


def text_of(h: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", h or ""))
    t = re.sub(r"\s+", " ", t).strip()
    t = re.split(r"A force main is a sewer line|About MSD Project Clear|About the Metropolitan St\. Louis Sewer", t)[0]
    # several older posts repeat their first sentence (the excerpt and the body)
    ss = sentences(t)
    if len(ss) > 1 and ss[0] == ss[1]:
        t = " ".join(ss[1:])
    return common.scrub_names(common.scrub_text(common.strip_house_numbers(t))).strip()


def pub_local(p: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(p["date_gmt"]).replace(tzinfo=timezone.utc).astimezone(TZ)
    except (KeyError, TypeError, ValueError):
        return None


def event_day(text: str, pub: date) -> tuple[date | None, str | None, str | None]:
    """(day, the sentence it came from, how it was read)."""
    for s in sentences(text)[:6]:
        d = find_date(s, pub)
        if d:
            return d, s, "date"
        if re.search(r"\byesterday\b|\blast night\b", s, re.I):
            return pub - timedelta(days=1), s, "yesterday"
        m = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", s, re.I)
        if m and re.search(r"discover|occur|happen|report|notic|found|break|overflow|spill|start|began", s, re.I):
            wd = WEEKDAYS.index(m.group(1).lower())
            back = (pub.weekday() - wd) % 7
            return pub - timedelta(days=back), s, "weekday"
    return None, None, None


def start_kind(s: str | None) -> str:
    if not s:
        return "publication"
    for k, rx in (("discovered", r"discover|noticed|found"), ("reported", r"report|alerted|call"),
                  ("started", r"start|began|begin"), ("occurred", r"occur|happen|broke|break")):
        if re.search(rx, s, re.I):
            return k
    return "stated"


def is_notice(p: dict) -> bool:
    title = html.unescape(p["title"]["rendered"])
    return bool(OWN_PATH.search(p["link"]) and NOTICE.search(title) and not NOT_EVENT.search(title))


def record(p: dict, at: str) -> dict:
    title = common.strip_house_numbers(html.unescape(p["title"]["rendered"])).strip()
    text = text_of(p["content"]["rendered"])
    pub = pub_local(p)
    if pub is None:
        raise ValueError(f"post {p.get('id')} has no publication time")
    pday = pub.date()
    day, sent, how = event_day(text, pday)
    kind = start_kind(sent)
    if day is None:
        start, prec = pday.isoformat(), "day"
    else:
        tm = TIME.search(sent or "")
        if tm:
            h, mi = clock(tm)
            start, prec = datetime(day.year, day.month, day.day, h, mi, tzinfo=TZ).isoformat(), "minute"
        else:
            start, prec = day.isoformat(), "day"
    ws = waters(text)
    if re.search(r"\bRiver des Peres\b", text) and "River des Peres" not in ws:
        ws.insert(0, "River des Peres") if re.search(r"(?:into|reach\w*|enter\w*) the River des Peres", text) \
            else ws.append("River des Peres")
    avoid = AVOID.search(text)
    if avoid:
        for w in waters(avoid.group(0).replace("avoid", "flows into")) or []:
            if w not in ws:
                ws.append(w)
    v, flag, vtext = volume(text)
    plant = bool(re.search(r"treatment plant", title, re.I))
    raw = {"state": "MO", "time_zone": "America/Chicago", "place_key": place_key(title),
           "place_key_version": PLACE_KEY_VERSION,
           "is_follow_up": bool(FOLLOW_UP.search(title)), "start_kind": kind, "day_read_from": how,
           "start_is_upper_bound": kind in ("discovered", "reported", "publication", "stated"),
           "start_basis": ("the post gives no day for the overflow: dated to the post's own day, on or before which it "
                           "happened" if day is None else
                           f"the day the post gives ({how}); a {kind} time is not necessarily the overflow's start"
                           if kind in ("discovered", "reported") else f"the day the post gives ({how})"),
           "waters_named": ws, "reached_water": (False if re.search(r"did not reach|never reached|before it reached",
                                                                      text, re.I) and not ws else (True if ws else None)),
           "volume_text": vtext, "provenance": "operator", "_placement": "named_water_only", "modified_gmt": p.get("modified_gmt"),
           "counties": ["St. Louis County", "St. Louis city"],
           "time_basis": "MSD's days and times, read as Central time (America/Chicago)"}
    return event(
        source_id=SOURCE_ID, source_record_id=str(p["id"]), event_type="plant_bypass" if plant else "sso",
        status="unknown", discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER,
        waterbody_text=water_text(ws), started_at=start, time_precision=prec,
        published_at=(datetime.fromisoformat(p["date_gmt"]).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                      if p.get("date_gmt") else None),
        fetched_at=at, material="wastewater", volume_gal=v, volume_text=vtext, estimate_flag=flag,
        authority=AUTHORITY, advice_text=safe_text(avoid.group(0).strip()) if avoid else None,
        source_url=permalink(p), raw=raw)


def permalink(p: dict) -> str:
    """msdprojectclear.org/?p=<id>, the post's numeric permalink, so a name or address in its slug is never kept
    (verification P1-4); the post's address only when it has no id."""
    return safe_link(p["link"], f"https://msdprojectclear.org/?p={p['id']}" if p.get("id") else None)


PLACE_KEY_VERSION = 2


def place_key(title: str) -> str:
    """The key that ties a follow-up post to its first post: the last place the title names, read from the scrubbed
    title (safe_text), so a person's name in a title never becomes part of the key (verification P1-4)."""
    title = safe_text(common.strip_house_numbers(title or "")) or ""
    title = title.replace("[name removed]", " ")
    title = re.sub(r"\s*\b(?:completed?|update[ds]?|halted)\b\s*$", "", title, flags=re.I).strip(" :-")
    m = re.search(r".*\b(?:in|near|at|into|along)\s+(?:the\s+)?([A-Z][\w .'-]+)$", title, re.I)   # the last place
    return re.sub(r"[^a-z]", "", (m.group(1) if m else title).lower())


def link_follow_ups(recs: dict[str, dict]) -> int:
    n = 0
    firsts = [r for r in recs.values() if not r["raw"].get("is_follow_up")]
    for r in recs.values():
        if not r["raw"].get("is_follow_up"):
            continue
        k = r["raw"].get("place_key")
        if not k:                                     # no key, no tie (never every keyless post to every other)
            continue
        d = datetime.fromisoformat(r["started_at"][:10])
        cands = [f for f in firsts if f["raw"].get("place_key") == k and
                 0 <= (d - datetime.fromisoformat(f["started_at"][:10])).days <= 14]
        if not cands:
            continue
        f = max(cands, key=lambda f: f["started_at"])
        r["duplicate_of"] = f["event_id"]
        f["raw"].setdefault("follow_ups", [])
        if r["source_url"] not in f["raw"]["follow_ups"]:
            f["raw"]["follow_ups"].append(r["source_url"])
        n += 1
    return n


def run(pages: list[list[dict]], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    for r in recs.values():
        if r["raw"].get("place_key_version") != PLACE_KEY_VERSION:
            # a key made by an earlier version from the unscrubbed title can hold a name: remade from the title when
            # the save still has it, else dropped (the post's next read remakes it); verification P1-4
            if r["raw"].get("title"):
                r["raw"]["place_key"] = place_key(r["raw"]["title"])
            else:
                r["raw"].pop("place_key", None)
            r["raw"]["place_key_version"] = PLACE_KEY_VERSION
        r["raw"].pop("title", None)                   # the post title is no longer kept (re-review P1-9)
        migrate_water_text(r)
        r["advice_text"] = safe_text(r.get("advice_text"))
        r["source_url"] = safe_link(r.get("source_url") or "", f"https://msdprojectclear.org/?p={r.get('source_record_id')}")
    stats = {"posts": 0, "own_posts": 0, "notices": 0}
    for page in pages:
        for p in page:
            stats["posts"] += 1
            stats["own_posts"] += bool(OWN_PATH.search(p.get("link") or ""))
            if not is_notice(p):
                continue
            stats["notices"] += 1
            r = record(p, at)
            old = recs.get(r["event_id"])
            r["raw"]["first_seen_at"] = (old or {}).get("raw", {}).get("first_seen_at") or at
            recs[r["event_id"]] = r
    for r in recs.values():
        r["duplicate_of"] = None
    stats["follow_ups_linked"] = link_follow_ups(recs)
    for r in recs.values():
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return out, stats


def safe_posts(page: list[dict]) -> list[dict]:
    return [{"id": p["id"], "date_gmt": p.get("date_gmt"), "modified_gmt": p.get("modified_gmt"), "link": permalink(p),
             "place_key": place_key(common.strip_house_numbers(html.unescape(p["title"]["rendered"]))),
             } for p in page if is_notice(p)]


def fetch(backfill: bool) -> list[list[dict]]:
    out = []
    for n in range(1, 30 if backfill else 2):
        r = requests.get(API, params={"per_page": 100 if backfill else 50, "page": n, "_fields": FIELDS},
                         headers=HEADERS, timeout=(20, 180))
        if r.status_code == 400 and n > 1:          # past the last page
            break
        r.raise_for_status()
        out.append(r.json())
        if n >= int(r.headers.get("X-WP-TotalPages") or 1):
            break
    save_raw(SOURCE_ID, json.dumps([x for page in out for x in safe_posts(page)], ensure_ascii=False, indent=1), "json")
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            pages = [json.loads(Path(a).read_text()) for a in argv[argv.index("--file") + 1:] if not a.startswith("--")]
        else:
            pages = fetch("--backfill" in argv)
        # parsing and reconciliation inside the handler: a post without its publication time, or a malformed one,
        # fails the run with the earlier records kept, never escapes without a health write (re-review P2-4)
        recs, stats = run(pages, prev, now_iso())
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
        write_events(SOURCE_ID, [], ok=False, error=error_detail(e))
        print(f"{SOURCE_ID}: {error_detail(e)}", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": HOME, "api": API, **stats,
        "credit": "Metropolitan St. Louis Sewer District (MSD Project Clear), alerts and news releases",
        "caveat": ("MSD posts some of its overflows; no rule requiring the posts was found, so an overflow with no post "
                   "is not shown here. MSD gives the day it found an overflow, seldom a time and never an end."),
        "cadence": "every refresh (the newest 50 posts); --backfill reads the whole archive"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
