"""MDEQ water contact advisories (Mississippi): the advisories the Mississippi Department of Environmental Quality issues
and lifts by news release for streams and rivers after sewage discharges, as dated advisory records.

Source
  https://www.mdeq.ms.gov/category/news-release/feed/ (registry: ms-mdeq-water-contact-advisories), MDEQ's news
  releases as RSS (the ten latest), no key; each release's own page for its text. MDEQ keeps no list of the advisories
  in effect: a release issues one ("Water Contact Advisory Issued for Section of Trahon Creek", 2026-09-02) and a
  later release lifts it ("MDEQ Lifts Water Contact Advisories for Long Beach and Biloxi East Central Beach",
  2026-09-01). No law requires the releases; they are MDEQ's practice.

Record rules
  - A release is an issue when its title reads "Water Contact Advisory Issued for <waters>" (or "MDEQ Issues Water
    Contact Advisory for ..."), a lift when it reads "... Lifts Water Contact Advisor(y|ies) for <waters>"; every other
    release (air quality, programmes) is not read. The waters are the title's, split at commas and "and" ("Section
    of" dropped). A release whose waters are all beaches is left to MDEQ's beach layer (ingest/ms_mdeq_beaches.py):
    since 2026-09-08 routine beach advisories go to the layer and signs only.
  - An issue opens one record: event_type beach_advisory (the beach and advisory category, docs/plan.md §3: a water
    contact advisory, not a discharge report), status advisory_active, started_at the release's date in Central
    time (time_precision day: MDEQ gives the day it issues the advisory), published_at and reported_at the feed's
    pubDate, advice_text MDEQ's own sentence ("MDEQ recommends that people avoid ..."), raw.release_text the
    release's paragraphs. The point is the release's own: the first "(32.194572 N, 90.250330 W)" its text gives
    (coord_source "source"); a release with none has no point.
  - A lift ends every open record one of whose waters it names: status advisory_lifted, ended_at the lift release's
    date (day), raw.lifted_by its title, link and date.
  - MDEQ lifts by release, so an advisory stays MDEQ's word until a lift is published. Each run that reads the feed
    without error and finds no lift for an open record re-confirms it: raw._last_seen_in_source is that run's fetch
    time and raw.confirmed_by says so (source_updated_at stays null: the feed gives no update time) (the status build keeps an advisory red while its source re-confirms it). A failed run
    confirms nothing, so an advisory whose feed stops answering ages out after the status build's 14 days.
  - STANDING: advisories in effect that no release in the feed issued, each cited to the release that says so. One on
    2026-11-07: "the longstanding water contact advisory for the section of the Pearl River from Hanging Moss Creek to
    the Byram Swinging bridge remains in effect" (the 2026-09-02 release). Its start is not stated: started_at is that
    release's date, the earliest date the record can stand on, and raw.start_basis says the advisory began earlier.
    Its point is the stretch's upstream end, the mouth of Hanging Moss Creek in the USGS Geographic Names Information
    System (GNIS 670883, Streams (Mouth) layer); the downstream end, the Byram Swinging Bridge, is the point of its
    National Register nomination (raw.stretch.to; see "The water" below). It is lifted like any other.
  - History: the feed holds ten releases, so the previous run's records are carried and updated; a record is never
    dropped because its release left the feed.
  - The water (2026-11-07 final audit): an advisory names its water, so it colours that water, not only a point.
    raw.advisory_extent is "named_water" (build/status.py then puts its interval on the water it is placed on and
    keeps its marker where the water is not filled; on a river or stream with no stretch it is a point only,
    status.advisory_on_river); raw.advisory_noun "Water contact advisory"
    is the label;
    raw.stretch gives the ends the release names ("from the culvert at ... to its confluence with the Pearl River"),
    the release's own point at the upstream end. Placement is by the water's name (waterbody_text), so a water whose
    record does not exist yet (Trahon Creek before the report-names pass) is tied when the record appears; the Pearl
    River's standing record also carries its slug (pearl-river-ms, the one Mississippi record of that name). When both
    ends have a public point the record carries `stretch` ({water, start, end}, each end with its point, basis and
    citation; docs/plan.md §3): build/reaches.py traces it from the upstream end down NHDPlus to the flowline point
    nearest the downstream end (reach kind "advisory_stretch") and build/status.py colours that stretch, not the
    whole river. The Pearl River's ends: the mouth of Hanging Moss Creek (GNIS 670883) and the Byram Bridge's National
    Register nomination (NRHP 79003427: UTM 15 759900 E 3563150 N, NAD 1927). A release whose downstream end has no
    point ("its confluence with the Pearl River") has no `stretch` and colours its whole water. These fields are
    refreshed on carried records.

Privacy: the feed's dc:creator (an MDEQ staff name) is never read; only titles, links, dates and the release text are,
and data/raw keeps only those fields of the feed (safe_feed), never the response.
Run from pipeline/:  python -m ingest.ms_mdeq_water_contact [--file feed.xml [--pages DIR]]
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "ms-mdeq-water-contact-advisories"
FEED = "https://www.mdeq.ms.gov/category/news-release/feed/"
TZ = ZoneInfo("America/Chicago")
AUTHORITY = "Mississippi Department of Environmental Quality (water contact advisory)"
ISSUE = re.compile(r"^(?:MDEQ\s+)?(?:Issues?\s+)?(?:a\s+)?Water Contact Advisor(?:y|ies)\s+(?:Issued\s+)?for\s+(.+?)\s*$", re.I)
LIFT = re.compile(r"\bLift(?:s|ed)?\s+(?:the\s+)?Water Contact Advisor(?:y|ies)\s+(?:for|on)\s+(.+?)\s*$", re.I)
COORD = re.compile(r"\((\d{2}\.\d+)\s*N,\s*(\d{2,3}\.\d+)\s*W\)")
# "The advisory covers ... from the culvert at the Interstate 55 frontage road (32.194572 N, 90.250330 W) to its
# confluence with the Pearl River."
SPAN = re.compile(r"\bcovers\b.*?\bfrom\s+(?:the\s+)?(.+?)\s+to\s+(?:its\s+|the\s+)?(.+?)\.(?:\s|$)", re.I)
NOUN = "Water contact advisory"
EXTENT = "named_water"
STANDING = [{
    "key": "pearl-river-hanging-moss-creek-to-byram-swinging-bridge",
    "waters": ["Pearl River"],
    "waterbody_text": "Pearl River",   # the stretch it covers is raw.stretch
    "cited_url": "https://www.mdeq.ms.gov/water-contact-advisory-issued-for-section-of-trahon-creek/",
    "cited_date": "2026-09-02",
    "quote": ("The longstanding water contact advisory for the section of the Pearl River from Hanging Moss Creek to the "
              "Byram Swinging bridge remains in effect."),
    "advice": ("MDEQ recommends that people avoid water contact recreational activities such as swimming, wading and "
               "fishing in these waters."),
    "point": (32.351817, -90.112036),
    "water_slugs": ["pearl-river-ms"],     # data/waters-ms.json: the one Mississippi record named Pearl River
    # the bases of the two points for the traced stretch (the record's `stretch`, docs/plan.md §3)
    "basis": {"from": "the mouth point of Hanging Moss Creek in the USGS Geographic Names Information System "
                      "(feature 670883, Streams (Mouth) layer)",
              "to": "the UTM reference of the bridge's National Register nomination (zone 15, 759900 E, 3563150 N, "
                    "NAD 1927), read as latitude and longitude"},
    "stretch": {"from": {"name": "mouth of Hanging Moss Creek", "lat": 32.351817, "lon": -90.112036,
                         "source": "USGS GNIS 670883, Streams (Mouth)",
                         "url": "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/670883"},
                # the bridge's National Register nomination (Byram Bridge, NRHP 79003427; MDAH Historic Sites Survey,
                # 1978) gives UTM zone 15, 759900 E, 3563150 N (NAD 1927), read here as latitude and longitude; the
                # nomination's NPS copy: https://npgallery.nps.gov/NRHP/GetAsset/NRHP/79003427_text
                "to": {"name": "Byram Swinging Bridge", "lat": 32.17657, "lon": -90.24366,
                       "source": ("National Register of Historic Places nomination, Byram Bridge (reference 79003427), "
                                  "UTM 15 759900 E 3563150 N, NAD 1927"),
                       "url": "https://npgallery.nps.gov/NRHP/GetAsset/NRHP/79003427_text"}},
}]


def items(body: bytes) -> list[dict]:
    """[{title, link, date}] of an RSS body (no XML parser; dc:creator is never read)."""
    t = body.decode("utf-8", "replace")
    out = []
    for m in re.finditer(r"(?is)<item\b[^>]*>(.*?)</item>", t):
        blk = m.group(1)

        def tag(n):
            x = re.search(rf"(?is)<{n}\b[^>]*>(.*?)</{n}>", blk)
            v = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", x.group(1)) if x else ""
            return re.sub(r"\s+", " ", html.unescape(html.unescape(v))).strip()
        out.append({"title": tag("title"), "link": tag("link"), "date": tag("pubDate")})
    return out


def kind(title: str) -> tuple[str | None, list[str]]:
    """('issue' | 'lift' | None, the waters the title names)."""
    for k, pat in (("lift", LIFT), ("issue", ISSUE)):
        m = pat.search(title or "")
        if m:
            w = re.sub(r"(?i)^(?:a\s+|the\s+)?section\s+of\s+(?:the\s+)?", "", m.group(1)).strip(" .")
            return k, [x.strip() for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", w) if x.strip()]
    return None, []


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def page_paragraphs(body: str) -> list[str]:
    """The release's paragraphs (the post content), tags removed."""
    m = re.search(r'(?is)class="col-md-12 post-content">(.*?)(?:<div class="col-md-12 more-news"|</article>)', body)
    blk = m.group(1) if m else body
    paras = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip()
             for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", blk)]
    return [p for p in paras if p]


def release_day(date: str) -> str | None:
    try:
        return parsedate_to_datetime(date).astimezone(TZ).date().isoformat()
    except (TypeError, ValueError):
        return None


def release_iso(date: str) -> str | None:
    try:
        return parsedate_to_datetime(date).astimezone(TZ).isoformat()
    except (TypeError, ValueError):
        return None


def stretch_of(paras: list[str] | None) -> dict | None:
    """The ends the release names ('covers ... from X (point) to Y'), the upstream end with the release's point."""
    for p in paras or []:
        m = SPAN.search(p)
        if m:
            c = COORD.search(m.group(1))
            frm = re.sub(r"\s*\([^)]*\)", "", m.group(1)).strip(" ,")
            return {"from": {"name": frm, "lat": float(c.group(1)) if c else None,
                             "lon": -float(c.group(2)) if c else None, "source": "the release"},
                    "to": {"name": m.group(2).strip(" ,"), "lat": None, "lon": None, "source": "the release"}}
    return None


def traced_stretch(raw_stretch: dict | None, water: str | None, basis: dict | None = None) -> dict | None:
    """The record's `stretch` (common.OPTIONAL_EVENT_FIELDS; docs/plan.md §3) when both ends the release names have a
    public point: {water, start, end}, each end {name, lat, lon, basis, source, url}; else None (an end without a
    point, such as "its confluence with the Pearl River", leaves the advisory on its whole water)."""
    ends = {}
    for k, side in (("from", "start"), ("to", "end")):
        e = (raw_stretch or {}).get(k) or {}
        if not isinstance(e.get("lat"), (int, float)) or not isinstance(e.get("lon"), (int, float)):
            return None
        ends[side] = {"name": e.get("name"), "lat": e["lat"], "lon": e["lon"],
                      "basis": (basis or {}).get(k) or ("the release's own coordinates" if e.get("source") == "the release"
                                                        else None),
                      "source": e.get("source"), "url": e.get("url")}
    return {"water": water, **ends}


def water_fields(r: dict, s: dict | None = None) -> dict:
    """Mark a record as colouring the water it names (refreshed on carried records too)."""
    r["raw"]["advisory_extent"], r["raw"]["advisory_noun"] = EXTENT, NOUN
    if s is not None:
        r["raw"]["stretch"] = s["stretch"]
        if s.get("water_slugs"):
            r["water_slugs"], r["water_match"] = list(s["water_slugs"]), "name"
    elif not r["raw"].get("stretch"):
        sp = stretch_of(r["raw"].get("release_text"))
        if sp:
            r["raw"]["stretch"] = sp
    waters = r["raw"].get("waters") or []
    st = traced_stretch(r["raw"].get("stretch"), waters[0] if len(waters) == 1 else None, (s or {}).get("basis"))
    if st:
        r["stretch"] = st
    else:
        r.pop("stretch", None)
    return r


def issue_record(it: dict, waters: list[str], paras: list[str] | None) -> dict:
    text = " ".join(paras or [])
    c = COORD.search(text)
    lat, lon = (float(c.group(1)), -float(c.group(2))) if c else (None, None)
    advice = next((p for p in paras or [] if re.search(r"\brecommends\b", p, re.I)), None)
    day = release_day(it["date"])
    return event(
        source_id=SOURCE_ID, source_record_id=f"{slug('-'.join(waters))}-{day}", event_type="beach_advisory",
        status="advisory_active", waterbody_text="; ".join(waters), lat=lat, lon=lon,
        coord_source="source" if c else None, started_at=day, time_precision="day",
        reported_at=release_iso(it["date"]), published_at=release_iso(it["date"]), authority=AUTHORITY,
        advice_text=advice, source_url=it["link"] or FEED,
        raw={"state": "MS", "title": it["title"], "waters": waters, "release_text": paras,
             "page_read": paras is not None,
             "time_basis": "day: the date of MDEQ's release issuing the advisory (Central time)",
             "coords_basis": "the release's own coordinates" if c else "the release gives no point"})


def standing_record(s: dict) -> dict:
    lat, lon = s["point"]
    return event(
        source_id=SOURCE_ID, source_record_id=s["key"], event_type="beach_advisory", status="advisory_active",
        waterbody_text=s["waterbody_text"], lat=lat, lon=lon, coord_source="gnis", started_at=s["cited_date"],
        time_precision="day", reported_at=s["cited_date"], published_at=s["cited_date"], authority=AUTHORITY,
        advice_text=s["advice"], source_url=s["cited_url"],
        raw={"state": "MS", "waters": s["waters"], "quote": s["quote"], "stretch": s["stretch"],
             "start_basis": ("MDEQ's release of this date says the advisory 'remains in effect'; it began earlier, "
                             "on a date the release does not give"),
             "time_basis": "day: the date of the release that says the advisory is in effect"})


def poll_times(r: dict) -> None:
    """A carried record from before 2026-11-07 had each run's fetch time as source_updated_at; the feed gives no
    update time, so that field is null and the last poll that found no lift is raw._last_seen_in_source."""
    if r.get("source_updated_at"):
        prev = r["raw"].get("_last_seen_in_source")
        r["raw"]["_last_seen_in_source"] = max(x for x in (prev, r["source_updated_at"]) if x)
        r["source_updated_at"] = None


def safe_feed(body: bytes) -> bytes:
    """What is kept of a fetched feed in data/raw: the fields this module reads (title, link, date) as JSON, never the
    response itself (its dc:creator is an MDEQ staff name; SOL wave 2 P1-5)."""
    return json.dumps({"url": FEED, "items": items(body)}, ensure_ascii=False, indent=1).encode()


def run(feed: bytes, pages: dict[str, str | None], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    """(records, stats) from the feed, the release pages ({link: html or None}) and the previous records."""
    recs = {r["event_id"]: r for r in prev}
    stats = {"releases": 0, "issues": 0, "lifts": 0, "beach_left_to_layer": 0, "lifted": 0}
    its = items(feed)
    stats["releases"] = len(its)
    for s in STANDING:
        r = standing_record(s)
        water_fields(recs.setdefault(r["event_id"], r), s)
    lifts = []
    for it in sorted(its, key=lambda x: release_iso(x["date"]) or ""):
        k, waters = kind(it["title"])
        if not k:
            continue
        if all(re.search(r"\bbeach\b", w, re.I) for w in waters):
            stats["beach_left_to_layer"] += 1
            continue
        if k == "lift":
            stats["lifts"] += 1
            lifts.append((it, waters))
            continue
        stats["issues"] += 1
        body = pages.get(it["link"])
        r = issue_record(it, waters, page_paragraphs(body) if body else None)
        if r["event_id"] in recs:
            old = recs[r["event_id"]]
            if not old["raw"].get("page_read") and r["raw"]["page_read"]:   # the page was out last time
                r.update(status=old["status"], ended_at=old.get("ended_at"))
                r["raw"]["lifted_by"] = old["raw"].get("lifted_by")
                recs[r["event_id"]] = r
            continue
        recs[r["event_id"]] = r
    for it, waters in lifts:
        day = release_day(it["date"])
        names = {key(w) for w in waters}
        for r in recs.values():
            if r["status"] != "advisory_active" or not day or (r.get("started_at") or "") > day:
                continue
            if names & {key(w) for w in r["raw"].get("waters") or []}:
                r["status"], r["ended_at"] = "advisory_lifted", day
                r["raw"]["lifted_by"] = {"title": it["title"], "link": it["link"], "date": day}
                stats["lifted"] += 1
    standing = {s["key"] for s in STANDING}
    for r in recs.values():
        if r["source_record_id"] not in standing:
            water_fields(r)
        poll_times(r)
        if r["status"] == "advisory_active":
            r["raw"]["_last_seen_in_source"] = at      # our poll, never the source's time (SOL wave 2 P1-6)
            r["raw"]["confirmed_by"] = (f"MDEQ's news-release feed read at {at}: no release lifting this advisory among "
                                        f"its {len(its)} latest releases")
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    return out, stats


def fetch() -> tuple[bytes, dict[str, str | None]]:
    r = requests.get(FEED, headers=HEADERS, timeout=60)
    r.raise_for_status()
    save_raw(SOURCE_ID, safe_feed(r.content), "json")
    pages = {}
    for it in items(r.content):
        k, waters = kind(it["title"])
        if k == "issue" and it["link"] and not all(re.search(r"\bbeach\b", w, re.I) for w in waters):
            try:
                p = requests.get(it["link"], headers=HEADERS, timeout=60)
                pages[it["link"]] = p.text if p.ok else None
            except requests.RequestException:
                pages[it["link"]] = None
    return r.content, pages


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            feed = Path(argv[argv.index("--file") + 1]).read_bytes()
            pdir = Path(argv[argv.index("--pages") + 1]) if "--pages" in argv else None
            pages = {}
            for it in items(feed):
                f = pdir / f"{slug(it['link'].rstrip('/').rsplit('/', 1)[-1])}.html" if pdir else None
                pages[it["link"]] = f.read_text() if f and f.exists() else None
        else:
            feed, pages = fetch()
    except (requests.RequestException, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats = run(feed, pages, prev, now_iso())
    out = write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "url": FEED, **stats,
                                              "cadence": "every refresh; MDEQ releases a few times a month"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats['open']} in effect) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
