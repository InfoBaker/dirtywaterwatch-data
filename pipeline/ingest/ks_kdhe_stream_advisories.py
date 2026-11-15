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
    "not stated"; advice_text built from those facts (advice_of), never the description. raw.advisory_extent "named_water" and raw.advisory_noun "Stream
    advisory": it colours the waters the title names (waterbody_text the first, raw.waters all), in raw.county.
  - A rescission ends every open record one of whose waters it names: status advisory_lifted, ended_at its pubDate
    (raw.ended_at_precision minute), raw.lifted_by its title and link. A rescission with no issue on record is counted
    (rescissions_without_issue) and kept in meta, never turned into a record with an invented start.
  - One record per water the release names in its title or description (source_record_id the release id and the
    water), so a partial rescission lifts only the waters it names; a rescission lifts a water only in its own county.
  - A run that reads the feed re-confirms an open record (raw._last_seen_in_source the poll time; source_updated_at
    stays null) only while the feed still holds the record's own issuing release (by its aid): past that, a missing
    rescission is no evidence, so the advisory ages out after the status build's 14 days; a failed run confirms nothing.
  - A release read again is reconciled (revise): its current county, waters, cause and advice replace the saved ones,
    the earliest publication time stays the start; a water it no longer names ends at that read (poll precision,
    raw.revised_out), and a water it names again is open again (raw.revised_out_reads keeps the read that dropped it);
    a water KDHE rescinded stays lifted. A rescission that names no county, for a water open in more than one county, lifts none
    (rescissions_seen_ambiguous in meta).
  - raw.time_zone by the release's county (pipeline/zones.py kansas_zone); raw._placement "named_water_only".
  - The feed's offsets read -0600 in October as in November (KDHE's server states Central Standard Time year-round);
    the time is kept as stated, raw.offset_note says so.

Privacy: a release's description is never saved: the records keep the facts read from it (waters, county, cause)
and advice built from them; titles are scrubbed (safe_text); the raw save keeps the same facts (safe_feed).
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
from ingest.mo_kc_water_news import safe_text

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


CAUSE_TEXT = {"sewage": "after a sewage or wastewater discharge", "livestock waste": "after a livestock waste discharge",
              "not stated": "(KDHE's release states no cause this site reads)"}


def advice_of(w: str | None, county: str | None, cause: str) -> str:
    """The advice kept: built from the facts read (KDHE's level, the water, the county, the cause), never the release's
    own description, which can name people or places (re-review P1-9)."""
    where = " in ".join(x for x in (w, county) if x) or "the waters the release names"
    return f"KDHE stream advisory for {where} {CAUSE_TEXT[cause]}: avoid contact with the water until KDHE rescinds it."


def issue_records(it: dict, waters: list[str], county: str | None) -> list[dict]:
    """One record per water the release names (title and description), so each colours and lifts on its own."""
    at = iso(it["date"])
    desc = it["description"]
    aid = re.sub(r"\D", "", it["link"].rsplit("aid=", 1)[-1]) or key(it["title"])
    ws = list(dict.fromkeys(waters + [w for w in desc_waters(desc) if key(w) not in {key(x) for x in waters}]))
    out = []
    cause = cause_of(f"{it['title']} {desc}")
    for w in ws or [None]:
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"{aid}-{key(w)}" if w else aid, event_type="beach_advisory",
            status="advisory_active", waterbody_text=w, started_at=at, time_precision="minute", published_at=at,
            reported_at=at, authority=AUTHORITY, advice_text=advice_of(w, county, cause), source_url=it["link"],
            raw={"state": "KS", "time_zone": zones.kansas_zone(county=county), "title": safe_text(it["title"]),
                 "release": aid, "waters": [w] if w else [], "release_waters": ws, "county": county,
                 "cause": cause, "advisory_extent": "named_water",
                 "advisory_noun": "Stream advisory", "offset_note": OFFSET_NOTE, "_placement": "named_water_only",
                 "start_basis": "the time KDHE published the advisory; it may have begun earlier the same day",
                 "time_basis": "the feed's publication time (pubDate)"}))
    return out


REVISABLE = ("waterbody_text", "advice_text", "source_url")
FORBIDDEN_RAW = ("description", "text")


def migrate(r: dict) -> None:
    """An earlier save at the next read: the release's description never kept (re-review P1-8, P1-9)."""
    raw = r.setdefault("raw", {})
    for k in FORBIDDEN_RAW:
        raw.pop(k, None)
    raw["title"] = safe_text(raw.get("title"))
    if r.get("advice_text") and not str(r["advice_text"]).startswith("KDHE stream advisory for "):
        r["advice_text"] = advice_of(r.get("waterbody_text"), raw.get("county"), raw.get("cause") or "not stated")


def revise(old: dict, new: dict) -> None:
    """A release read again: its current words replace the saved ones (county, waters, cause, advice), its earliest
    publication time stays the start (a later pubDate never moves the start later), and the status is kept."""
    for k in REVISABLE:
        old[k] = new[k]
    if old.get("status") == "advisory_lifted" and old["raw"].get("revised_out") and not old["raw"].get("lifted_by"):
        # the release names this water again after a revision had dropped it (verification P1-2): the earlier end was
        # this site's reading of a revision, never KDHE's rescission, so the advisory is open again under KDHE's
        # release; the read that dropped it is kept in raw.revised_out_reads. A rescission (lifted_by) stays lifted
        old["raw"].setdefault("revised_out_reads", []).append(old.get("ended_at"))
        old["status"], old["ended_at"] = "advisory_active", None
        for k in ("revised_out", "ended_at_precision", "end_basis"):
            old["raw"].pop(k, None)
    for k in ("title", "waters", "release_waters", "county", "time_zone", "cause"):
        old["raw"][k] = new["raw"][k]
    if new.get("started_at") and new["started_at"] != old.get("started_at"):
        seen = old["raw"].setdefault("publication_times_seen", [old.get("started_at")])
        if new["started_at"] not in seen:
            seen.append(new["started_at"])
        first = min((t for t in seen if t), key=lambda t: iso_utc(t))
        old["started_at"] = old["published_at"] = old["reported_at"] = first


def iso_utc(t: str) -> str:
    from datetime import datetime, timezone
    return datetime.fromisoformat(t).astimezone(timezone.utc).isoformat()


def run(feed: bytes, prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    for r in recs.values():
        migrate(r)
    stats = {"releases": 0, "issues": 0, "rescissions": 0, "lifted": 0, "rescissions_without_issue": 0,
             "revised_out": 0, "rescissions_ambiguous": 0}
    its = items(feed)
    stats["releases"] = len(its)
    lifts, orphan, ambiguous = [], [], []
    present: set[str] = set()           # the issuing releases this read holds (re-review P1-4)
    for it in sorted(its, key=lambda x: iso(x["date"]) or ""):
        k, waters, county = kind(it["title"])
        if k == "issue":
            stats["issues"] += 1
            now = issue_records(it, waters, county)
            aid = now[0]["raw"]["release"]
            present.add(aid)
            ids = {r["event_id"] for r in now}
            for r in now:
                if r["event_id"] in recs:
                    revise(recs[r["event_id"]], r)
                else:
                    recs[r["event_id"]] = r
            for r in recs.values():
                # a water the release no longer names (KDHE revised it): its advisory ends at this read, at poll
                # precision, never left open beside the water the release now names
                if r["raw"].get("release") == aid and r["event_id"] not in ids and r["status"] == "advisory_active":
                    r.update(status="advisory_lifted", ended_at=at)
                    r["raw"].update(ended_at_precision="poll", revised_out=True,
                                    end_basis=("KDHE's release no longer names this water at this read: the advisory "
                                               "is not shown for it after this read; not KDHE's lift time"))
                    stats["revised_out"] += 1
        elif k == "lift":
            stats["rescissions"] += 1
            lifts.append((it, waters + desc_waters(it["description"]), county))
    for it, waters, county in lifts:
        when = iso(it["date"])
        names = {key(w) for w in waters}
        cands = [r for r in recs.values()
                 if r["status"] == "advisory_active" and (r.get("started_at") or "") <= (when or "")
                 and names & {key(w) for w in r["raw"].get("waters") or []}
                 and not (county and r["raw"].get("county") and county != r["raw"]["county"])]
        if not county and len({r["raw"].get("county") for r in cands}) > 1:
            # a rescission that names no county, for a water name open in several counties: which one it lifts is not
            # known, so none is lifted (they age out unconfirmed) and the rescission is kept in meta
            ambiguous.append({"title": it["title"], "link": it["link"], "date": when,
                              "counties": sorted(str(r["raw"].get("county")) for r in cands)})
            continue
        for r in cands:
            r["status"], r["ended_at"] = "advisory_lifted", when
            r["raw"].update(ended_at_precision="minute", lifted_by={"title": it["title"], "link": it["link"],
                                                                     "date": when})
            r["raw"].pop("confirmed_by", None)
            stats["lifted"] += 1
        if not cands and not any((r["raw"].get("lifted_by") or {}).get("link") == it["link"] for r in recs.values()):
            orphan.append({"title": it["title"], "link": it["link"], "date": when})
    stats["rescissions_without_issue"] = len(orphan)
    stats["rescissions_ambiguous"] = len(ambiguous)
    for r in recs.values():
        # a read confirms an open advisory only while the feed holds its own issuing release (re-review P1-4): an
        # unrelated older item proves nothing about it; past that the status build's 14-day aging applies
        if r["status"] == "advisory_active" and r["raw"].get("release") in present:
            r["raw"]["_last_seen_in_source"] = at
            r["raw"]["confirmed_by"] = (f"KDHE's news flash feed read at {at}: it still holds the issuing release and "
                                        "no rescission")
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    stats["rescissions_seen_without_issue"] = orphan
    stats["rescissions_seen_ambiguous"] = ambiguous
    return out, stats


def safe_feed(body: bytes) -> bytes:
    """Only the stream advisory releases, never the rest of KDHE's news (Astra 2026-11-14 P1-9)."""
    keep = []
    for i in items(body):
        k, waters, county = kind(i["title"])
        if not k:
            continue
        # the facts read, never the release's description (re-review P1-9)
        keep.append({"title": safe_text(i["title"]), "link": i["link"], "date": i["date"], "kind": k,
                     "waters": list(dict.fromkeys(waters + desc_waters(i["description"]))), "county": county,
                     "cause": cause_of(f"{i['title']} {i['description']}")})
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
    except (requests.RequestException, OSError, ET.ParseError, ValueError, KeyError, TypeError, IndexError) as e:
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
