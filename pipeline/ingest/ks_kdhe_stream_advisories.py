"""KDHE stream advisories (Kansas): the water-contact advisories the Kansas Department of Health and Environment issues
and rescinds by news flash for streams, rivers and lake inlets after a sewage or other wastewater discharge, as dated
advisory records with KDHE's own window.

Source
  https://www.kdhe.ks.gov/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml (registry: ks-kdhe-stream-advisories), KDHE's
  news flash feed (CivicPlus): about the last month of releases (42 items on 2026-11-14), each with its title, link
  (CivicAlerts.aspx?aid=N), pubDate and a one-sentence description. The release pages, the news index and the rest of
  kdhe.ks.gov answer 403 to the identified client, so only the feed is read and the archive is what this module has
  kept since its first run (no backfill is possible: the window is the feed's). On 2026-11-14 the feed held one stream
  advisory release (a rescission, 2026-10-29); the January 29 and February 3, 2026 Lake Shawnee pair the research read
  is older than the feed. Most of the feed is boil water advisories (drinking water, never read) and the weekly
  blue-green algae release (read from KDHE's HAB layer instead, ks-kdhe-hab-status).

Record rules
  - A release is an issue when its title reads "Stream Advisory Issued for <waters> in <county> County" (or "KDHE
    Issues Stream Advisory for ..."), a rescission when it reads "Stream Advisory Rescinded for ..." or "Lifted"; every
    other release is not read.
  - An issue opens one record: event_type beach_advisory (the advisory category: a water contact advisory, not a
    discharge report), status advisory_active, started_at the release's pubDate (time_precision minute: the time KDHE
    published it, the latest the advisory can have begun; raw.start_basis), published_at the same, raw.cause "sewage"
    when the description names sewage or wastewater, "livestock waste" when it names livestock or manure, else
    "not stated"; advice_text KDHE's description. raw.advisory_extent "named_water" and raw.advisory_noun "Stream
    advisory": it colours the waters the title names (waterbody_text the first, raw.waters all), in raw.county.
  - A rescission ends every open record one of whose waters it names: status advisory_lifted, ended_at its pubDate
    (raw.ended_at_precision minute), raw.lifted_by its title and link. A rescission with no issue on record is counted
    (rescissions_without_issue) and kept in meta, never turned into a record with an invented start.
  - One record per water the release names in its title or description (source_record_id the release id and the
    water), so a partial rescission lifts only the waters it names; a rescission lifts a water only in its own county.
  - A run that reads the feed re-confirms an open record (raw._last_seen_in_source the poll time; source_updated_at
    stays null) only while the feed still holds the issuing release: past that, a missing rescission is no evidence,
    so the advisory ages out after the status build's 14 days; a failed run confirms nothing.
  - raw.time_zone by the release's county (pipeline/zones.py kansas_zone); raw._placement "named_water_only".
  - The feed's offsets read -0600 in October as in November (KDHE's server states Central Standard Time year-round);
    the time is kept as stated, raw.offset_note says so.

Privacy: the feed names no people; only titles, links, dates and descriptions are kept (safe_feed).
Run from pipeline/:  python -m ingest.ks_kdhe_stream_advisories [--file feed.xml]
"""
from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import common
import zones
from common import HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "ks-kdhe-stream-advisories"
FEED = "https://www.kdhe.ks.gov/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml"
AUTHORITY = "Kansas Department of Health and Environment (stream advisory)"
ISSUE = re.compile(r"^(?:KDHE\s+)?(?:Issues?\s+)?(?:a\s+)?Stream Advisor(?:y|ies)\s+(?:Issued\s+)?for\s+(.+?)\s*$", re.I)
LIFT = re.compile(r"Stream Advisor(?:y|ies)\s+(?:Rescinded|Lifted)\s+for\s+(.+?)\s*$|\b(?:Rescinds|Lifts)\s+Stream "
                  r"Advisor(?:y|ies)\s+for\s+(.+?)\s*$", re.I)
COUNTY = re.compile(r"\s+in\s+([A-Z][\w .]+?)\s+Count(?:y|ies)\s*$")
OFFSET_NOTE = "KDHE's feed gives -0600 year-round; the time is kept as the feed states it"


def items(body: bytes) -> list[dict]:
    root = ET.fromstring(body)
    return [{"title": " ".join(html.unescape(it.findtext("title") or "").split()), "link": (it.findtext("link") or "").strip(),
             "date": " ".join((it.findtext("pubDate") or "").split()),
             "description": html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or "")).strip()}
            for it in root.iter("item")]


def iso(date: str) -> str | None:
    try:
        return parsedate_to_datetime(date).isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def split_waters(s: str) -> tuple[list[str], str | None]:
    m = COUNTY.search(s)
    county = f"{m.group(1).strip()} County" if m else None
    s = COUNTY.sub("", s)
    parts = [p.strip() for p in re.split(r",\s*|\s+and\s+", s) if p.strip()]
    return [re.sub(r"^(?:the|a section of|section of|portions? of)\s+", "", p, flags=re.I) for p in parts], county


def kind(title: str) -> tuple[str | None, list[str], str | None]:
    m = LIFT.search(title)
    if m:
        w, c = split_waters(m.group(1) or m.group(2))
        return "lift", w, c
    m = ISSUE.match(title)
    if m:
        w, c = split_waters(m.group(1))
        return "issue", w, c
    return None, [], None


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def cause_of(text: str) -> str:
    if re.search(r"sewage|sewer|waste ?water treatment|wastewater", text, re.I):
        return "sewage"
    if re.search(r"livestock|manure|feedlot|animal waste", text, re.I):
        return "livestock waste"
    return "not stated"


DESC_WATERS = re.compile(r"\bfor\s+(.+?)(?:\s+(?:in|near|after|due|because)\b|[.;]|$)", re.I)


def desc_waters(desc: str) -> list[str]:
    """The waters a description lists after "for" ("... stream advisory for McIntyre Creek, Tuttle Creek Reservoir, the
    Big Blue River, and the Kansas River"); a title may name only the first (Astra 2026-11-14 P1-2)."""
    m = DESC_WATERS.search(desc or "")
    if not m:
        return []
    ws, _ = split_waters(re.sub(r",?\s+and\s+", ", ", m.group(1)))
    return [w for w in ws if re.search(r"\b(?:Creek|River|Lake|Reservoir|Branch|Fork|Inlet|Pond)\b", w)]


def issue_records(it: dict, waters: list[str], county: str | None) -> list[dict]:
    """One record per water the release names (title and description), so each colours and lifts on its own."""
    at = iso(it["date"])
    desc = it["description"]
    aid = re.sub(r"\D", "", it["link"].rsplit("aid=", 1)[-1]) or key(it["title"])
    ws = list(dict.fromkeys(waters + [w for w in desc_waters(desc) if key(w) not in {key(x) for x in waters}]))
    out = []
    for w in ws or [None]:
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"{aid}-{key(w)}" if w else aid, event_type="beach_advisory",
            status="advisory_active", waterbody_text=w, started_at=at, time_precision="minute", published_at=at,
            reported_at=at, authority=AUTHORITY, advice_text=desc or None, source_url=it["link"],
            raw={"state": "KS", "time_zone": zones.kansas_zone(county=county), "title": it["title"], "release": aid,
                 "waters": [w] if w else [], "release_waters": ws, "county": county,
                 "cause": cause_of(f"{it['title']} {desc}"), "advisory_extent": "named_water",
                 "advisory_noun": "Stream advisory", "offset_note": OFFSET_NOTE, "_placement": "named_water_only",
                 "start_basis": "the time KDHE published the advisory; it may have begun earlier the same day",
                 "time_basis": "the feed's publication time (pubDate)"}))
    return out


def run(feed: bytes, prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    stats = {"releases": 0, "issues": 0, "rescissions": 0, "lifted": 0, "rescissions_without_issue": 0}
    its = items(feed)
    stats["releases"] = len(its)
    oldest = min((iso(i["date"]) for i in its if iso(i["date"])), default=None)
    lifts, orphan = [], []
    for it in sorted(its, key=lambda x: iso(x["date"]) or ""):
        k, waters, county = kind(it["title"])
        if k == "issue":
            stats["issues"] += 1
            for r in issue_records(it, waters, county):
                recs.setdefault(r["event_id"], r)
        elif k == "lift":
            stats["rescissions"] += 1
            lifts.append((it, waters + desc_waters(it["description"]), county))
    for it, waters, county in lifts:
        when = iso(it["date"])
        names = {key(w) for w in waters}
        hit = False
        for r in recs.values():
            if r["status"] != "advisory_active" or (r.get("started_at") or "") > (when or ""):
                continue
            if county and r["raw"].get("county") and county != r["raw"]["county"]:
                continue                                   # the same creek name in another county is another water
            if names & {key(w) for w in r["raw"].get("waters") or []}:
                r["status"], r["ended_at"] = "advisory_lifted", when
                r["raw"].update(ended_at_precision="minute", lifted_by={"title": it["title"], "link": it["link"],
                                                                         "date": when})
                r["raw"].pop("confirmed_by", None)
                stats["lifted"] += 1
                hit = True
        if not hit and not any((r["raw"].get("lifted_by") or {}).get("link") == it["link"] for r in recs.values()):
            orphan.append({"title": it["title"], "link": it["link"], "date": when})
    stats["rescissions_without_issue"] = len(orphan)
    for r in recs.values():
        # a read confirms an open advisory only while the feed still reaches back to its issue: past that, a missing
        # rescission is no evidence (the feed keeps about a month), and the status build's 14-day aging applies
        if r["status"] == "advisory_active" and oldest and (r.get("started_at") or "") >= oldest:
            r["raw"]["_last_seen_in_source"] = at
            r["raw"]["confirmed_by"] = (f"KDHE's news flash feed read at {at}: it still holds the issuing release and "
                                        "no rescission")
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    stats["rescissions_seen_without_issue"] = orphan
    return out, stats


def safe_feed(body: bytes) -> bytes:
    """Only the stream advisory releases, never the rest of KDHE's news (Astra 2026-11-14 P1-9)."""
    keep = [i for i in items(body) if kind(i["title"])[0]]
    return json.dumps({"url": FEED, "items": keep}, ensure_ascii=False, indent=1).encode()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            feed = Path(argv[argv.index("--file") + 1]).read_bytes()
        else:
            r = requests.get(FEED, headers=HEADERS, timeout=(20, 120))
            r.raise_for_status()
            feed = r.content
            save_raw(SOURCE_ID, safe_feed(feed), "json")
        recs, stats = run(feed, prev, now_iso())
    except (requests.RequestException, OSError, ET.ParseError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": FEED, **stats,
        "credit": "Kansas Department of Health and Environment, news flash",
        "caveat": ("KDHE's stream advisories as its news feed carries them: about a month of releases, with the release "
                   "pages closed to automated reading, so an advisory issued before this site began reading the feed "
                   "is not shown."),
        "cadence": "every refresh"})
    print(f"{SOURCE_ID}: {len(recs)} records ({ {k: v for k, v in stats.items() if not isinstance(v, list)} }) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
