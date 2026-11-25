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
    Issues Stream Advisory for ...", "Stream and Lake Advisory Issued for ...", "Lake Advisory Issued for ..."), a
    rescission when it reads "... Advisory Rescinded for ..." or "Lifted"; a "Regional Advisory" (KDHE's June 26, 2026
    one for flooded waterways in eleven counties) is a regional issue: one record with no water, listed with the
    counties it names and never coloured on any water (raw.advisory_extent "regional"). Every other release is not
    read; a title with "Advisory" that is neither a boil water nor a blue-green algae release and is not read is
    counted in meta (unread_advisory_titles), so a new wording becomes visible (go-live audit 2026-11-15 P2-1).
  - Hand-entered releases (HAND_FILE, data/sources/ks-kdhe-stream-advisories-hand.json): an advisory issued before
    the feed's window, whose release page answers 403, entered by hand from the release's indexed text with its
    public address and date (go-live audit 2026-11-15 P1-1). Each row opens the same records as a feed issue, at the
    release's day (time_precision day: no time is invented), raw.hand_entry citing the row; it is confirmed at every
    read while no rescission is on record, so it never ages out with the feed window, and it is lifted only by a
    rescission read in the feed or a rescission entered in the row ("rescission": {date, url, title}).
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
    raw.revised_out), and a water it names again opens a new observed period, its own record (source_record_id
    "<release>-<water>-p<n>", raw.period_of the first, started_at the read that saw it named again, time_precision
    poll), so the earlier period keeps its end and the time between is never coloured; a water KDHE rescinded stays
    lifted. A rescission applies by its issuing release's publication time, never a period's own start: every
    rescission a read holds is reconciled before any period is opened, so a water named again in the read that holds
    its rescission is never reopened; a rescission read while the release no longer names the water is kept on that
    record (raw.rescinded_by), so a later read never reopens it; a period first seen after a rescission published
    earlier ends where it starts. A rescission that names no county, for a water open in more than one county, lifts none
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
from common import error_detail
from ingest.mo_kc_water_news import safe_text

SOURCE_ID = "ks-kdhe-stream-advisories"
FEED = "https://www.kdhe.ks.gov/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml"
AUTHORITY = "Kansas Department of Health and Environment (stream advisory)"
KINDS = r"(?:Stream\s+(?:and|&)\s+Lake|Stream|Lake)"
ISSUE = re.compile(r"^(?:KDHE\s+)?(?:Issues?\s+)?(?:a\s+)?" + KINDS + r"\s+Advisor(?:y|ies)\s+(?:Issued\s+)?for\s+(.+?)\s*$",
                   re.I)
LIFT = re.compile(KINDS + r"\s+Advisor(?:y|ies)\s+(?:Rescinded|Lifted)\s+for\s+(.+?)\s*$|\b(?:Rescinds|Lifts)\s+"
                  + KINDS + r"\s+Advisor(?:y|ies)\s+for\s+(.+?)\s*$", re.I)
REGIONAL = re.compile(r"^(?:KDHE\s+)?(?:Issues?\s+)?(?:a\s+)?Regional\s+Advisor(?:y|ies)\b(?:\s+(?:Issued\s+)?for\s+(.+?))?\s*$",
                      re.I)
REGIONAL_LIFT = re.compile(r"Regional\s+Advisor(?:y|ies)\s+(?:Rescinded|Lifted)|\b(?:Rescinds|Lifts)\s+Regional\s+Advisor",
                           re.I)
NOT_STREAM = re.compile(r"boil\s+water|blue[- ]green|algae|algal", re.I)
HAND_FILE = common.DATA_DIR / "sources" / "ks-kdhe-stream-advisories-hand.json"
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


COUNTIES = re.compile(r"\b((?:[A-Z][a-z]+\s+)?[A-Z][a-z]+(?:\s*,\s*(?:and\s+)?(?:[A-Z][a-z]+\s+)?[A-Z][a-z]+)*"
                      r"(?:\s+and\s+(?:[A-Z][a-z]+\s+)?[A-Z][a-z]+)?)\s+Counties\b")


def counties_of(text: str) -> list[str]:
    """The counties a regional release lists ("... in Allen, Bourbon and Neosho Counties"), each as "X County"."""
    out = []
    for m in COUNTIES.finditer(text or ""):
        for c in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", m.group(1)):
            c = re.sub(r"^(?:in|of|for)\s+", "", c.strip())
            if c and f"{c} County" not in out:
                out.append(f"{c} County")
    m = re.search(r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+County\b", text or "")
    if m and not out:
        out.append(f"{m.group(1)} County")
    return out


def kind(title: str) -> tuple[str | None, list[str], str | None]:
    if REGIONAL_LIFT.search(title):
        return "regional_lift", [], None
    m = REGIONAL.match(title)
    if m:
        return "regional", [], None
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
                 "description": desc, "release": aid, "waters": [w] if w else [], "release_waters": ws, "county": county,
                 "cause": cause, "advisory_extent": "named_water",
                 "advisory_noun": "Stream advisory", "offset_note": OFFSET_NOTE, "_placement": "named_water_only",
                 "start_basis": "the time KDHE published the advisory; it may have begun earlier the same day",
                 "time_basis": "the feed's publication time (pubDate)"}))
    return out


REVISABLE = ("waterbody_text", "advice_text", "source_url")
FORBIDDEN_RAW = ()


def migrate(r: dict) -> None:
    """An earlier save at the next read: the release's description never kept (re-review P1-8, P1-9)."""
    raw = r.setdefault("raw", {})
    for k in FORBIDDEN_RAW:
        raw.pop(k, None)
    raw["title"] = safe_text(raw.get("title"))



def revise(old: dict, new: dict) -> None:
    """A release read again: its current words replace the saved ones (county, waters, cause, advice), its earliest
    publication time stays the start (a later pubDate never moves the start later), and the status is kept."""
    for k in REVISABLE:
        old[k] = new[k]
    for k in ("title", "waters", "release_waters", "county", "time_zone", "cause"):
        old["raw"][k] = new["raw"][k]
    if old["raw"].get("period_of"):
        return          # a later observed period starts at the read that saw it named again, never at the release
    if new.get("started_at") and new["started_at"] != old.get("started_at"):
        seen = old["raw"].setdefault("publication_times_seen", [old.get("started_at")])
        if new["started_at"] not in seen:
            seen.append(new["started_at"])
        first = min((t for t in seen if t), key=lambda t: iso_utc(t))
        old["started_at"] = old["published_at"] = old["reported_at"] = first


def iso_utc(t: str) -> str:
    """UTC of a time; a hand entry's bare day ("2026-06-25") is taken as that day's first minute in Central time, so a
    rescission published later that day still applies to it."""
    from datetime import datetime, timezone
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t or ""):
        t = f"{t}T00:00:00-06:00"
    return datetime.fromisoformat(t).astimezone(timezone.utc).isoformat()


def base_of(r: dict) -> str:
    return r["raw"].get("period_of") or r["event_id"]


def reopened(prior: dict, new: dict, at: str, n: int) -> dict:
    """The release names a water again after a read that no longer named it (verification 2 P1-1): a new observed
    period, its own record, from this read (poll precision), so the earlier period keeps its end and the time between
    is never coloured; the release's publication time stays only on the first period."""
    r = json.loads(json.dumps(new))
    r["source_record_id"] = f"{new['source_record_id']}-p{n}"
    r["event_id"] = f"{SOURCE_ID}:{r['source_record_id']}"
    r["started_at"], r["time_precision"] = at, "poll"
    r["raw"].update(period_of=base_of(prior), period=n, start_basis=(
        "KDHE's release named this water again at this read, after an earlier read no longer named it: the advisory "
        "is shown from this read, not from the release's publication; the earlier period keeps its own end"))
    return r


def split_reopened(recs: dict) -> None:
    """An earlier save that reopened one record over a gap (raw.revised_out_reads): the first period ends at the read
    that dropped the water, and the open period starts no earlier than its last confirming read, so the gap between is
    never coloured (verification 2 P1-1)."""
    for r in list(recs.values()):
        reads = r["raw"].pop("revised_out_reads", None)
        if not reads or r["raw"].get("period_of"):
            continue
        again = r["raw"].get("_last_seen_in_source") or r.get("fetched_at")
        if again and (r["status"] == "advisory_active" or r["raw"].get("lifted_by")):
            nxt = reopened(r, r, again, 2)
            nxt.update(status=r["status"], ended_at=r.get("ended_at"))
            if nxt["ended_at"] and iso_utc(nxt["ended_at"]) < iso_utc(again):
                nxt["started_at"] = nxt["ended_at"]      # never a start after KDHE's own rescission
            for k in ("_last_seen_in_source", "confirmed_by", "lifted_by", "ended_at_precision"):
                if k in r["raw"]:
                    nxt["raw"][k] = r["raw"][k]
            recs[nxt["event_id"]] = nxt
        r.update(status="advisory_lifted", ended_at=reads[0])
        for k in ("lifted_by", "confirmed_by", "_last_seen_in_source"):
            r["raw"].pop(k, None)
        r["raw"].update(ended_at_precision="poll", revised_out=True, end_basis=REVISED_OUT_BASIS)


REVISED_OUT_BASIS = ("KDHE's release no longer names this water at this read: the advisory is not shown for it after "
                     "this read; not KDHE's lift time")


def rescinded(r: dict) -> bool:
    return bool(r["raw"].get("lifted_by") or r["raw"].get("rescinded_by"))


def issued_at(r: dict, recs: dict) -> str | None:
    """The issuing release's publication time: a later observed period's own start is a read, never the release."""
    base = recs.get(r["raw"].get("period_of") or "") or r
    return base.get("started_at") if not base["raw"].get("period_of") else None


def lift_applies(lift: tuple, r: dict, recs: dict) -> bool:
    """A rescission applies to a record of one of the waters it names, in its county (or any county when it names
    none), when it was published at or after the record's issuing release, whatever the record's own start."""
    it, waters, county = lift
    when, start = iso(it["date"]), issued_at(r, recs)
    return bool(when and start and iso_utc(start) <= iso_utc(when)
                and {key(w) for w in waters} & {key(w) for w in r["raw"].get("waters") or []}
                and not (county and r["raw"].get("county") and county != r["raw"]["county"]))


def county_clear(lift: tuple, cands: list[dict]) -> bool:
    """A rescission that names no county lifts only where its waters are held in one county."""
    return bool(lift[2]) or len({r["raw"].get("county") for r in cands}) <= 1


def rescinded_now(new: dict, lifts: list, recs: dict) -> bool:
    """A water named again in a read that also holds its rescission: never a new observed period."""
    for lift in lifts:
        same = [x for x in recs.values() if lift_applies(lift, x, recs)]
        if any(base_of(x) == new["event_id"] for x in same) and county_clear(lift, same):
            return True
    return False


def apply_lifts(lifts: list, recs: dict, stats: dict | None, orphan: list, ambiguous: list) -> None:
    """Each rescission ends every open record it applies to at KDHE's time (never before the record's own start: a
    period first seen after the rescission was published ends where it starts, so it is never coloured), and marks a
    water the release had already stopped naming (raw.rescinded_by), so it is never reopened by a later read
    (verification 3 P1-1). stats None: the reconciliation before the issues are read, which counts nothing."""
    for lift in lifts:
        it, _, county = lift
        when = iso(it["date"])
        cands = [r for r in recs.values() if r["status"] == "advisory_active" and lift_applies(lift, r, recs)]
        dropped = [r for r in recs.values() if r["status"] == "advisory_lifted" and r["raw"].get("revised_out")
                   and not rescinded(r) and lift_applies(lift, r, recs)]
        if not county_clear(lift, cands + dropped):
            # a rescission that names no county, for a water name held in several counties: which one it lifts is
            # not known, so none is lifted (they age out unconfirmed) and the rescission is kept in meta
            if stats is not None:
                ambiguous.append({"title": it["title"], "link": it["link"], "date": when,
                                  "counties": sorted({str(r["raw"].get("county")) for r in cands + dropped})})
            continue
        mark = {"title": it["title"], "link": it["link"], "date": when}
        for r in cands:
            late = iso_utc(when) < iso_utc(r["started_at"])
            r["status"], r["ended_at"] = "advisory_lifted", r["started_at"] if late else when
            r["raw"].update(ended_at_precision="minute", lifted_by=mark)
            if late:
                r["raw"]["end_basis"] = ("KDHE rescinded the advisory before this period was first seen: it ends where it "
                                         "starts, never shown after the rescission")
            r["raw"].pop("confirmed_by", None)
            if stats is not None:
                stats["lifted"] += 1
        for r in dropped:
            r["raw"]["rescinded_by"] = mark
        if stats is not None and not cands and not dropped and not any(
                (r["raw"].get("lifted_by") or r["raw"].get("rescinded_by") or {}).get("link") == it["link"]
                for r in recs.values()):
            orphan.append(mark)


def regional_record(it: dict) -> dict:
    """A regional advisory: one record with no water, listed with the counties it names, never coloured on a water."""
    at = iso(it["date"])
    aid = re.sub(r"\D", "", it["link"].rsplit("aid=", 1)[-1]) or key(it["title"])
    counties = counties_of(f"{it['title']} {it['description']}")
    cause = cause_of(f"{it['title']} {it['description']}")
    where = ", ".join(counties) if counties else "the counties the release names"
    return event(
        source_id=SOURCE_ID, source_record_id=aid, event_type="beach_advisory", status="advisory_active",
        waterbody_text=None, started_at=at, time_precision="minute", published_at=at, reported_at=at,
        authority=AUTHORITY, source_url=it["link"],
        advice_text=f"KDHE regional advisory for waters in {where} {CAUSE_TEXT[cause]}: avoid contact with the water "
                    "until KDHE rescinds it.",
        raw={"state": "KS", "time_zone": zones.kansas_zone(county=counties[0] if len(counties) == 1 else None),
             "title": safe_text(it["title"]), "release": aid, "waters": [], "release_waters": [], "county": None,
             "counties": counties, "cause": cause, "advisory_extent": "regional", "advisory_noun": "Regional advisory",
             "offset_note": OFFSET_NOTE, "_placement": "named_water_only",
             "start_basis": "the time KDHE published the advisory; it may have begun earlier the same day",
             "time_basis": "the feed's publication time (pubDate)"})


def hand_rows(path: Path | None = None) -> list[dict]:
    doc = read_json(path or HAND_FILE, {}) or {}
    return list(doc.get("releases") or [])


def hand_records(row: dict) -> list[dict]:
    """The records of a release entered by hand (module docstring): the same records a feed issue opens, at the
    release's day (day precision), cited to the release's public address, marked as entered by hand."""
    day = row["published"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError(f"hand-entered KDHE release {row.get('release')}: published must be a day (YYYY-MM-DD)")
    aid, county, cause = str(row["release"]), row.get("county"), row.get("cause") or "not stated"
    hand = {k: row.get(k) for k in ("release", "url", "other_urls", "published", "entered", "entered_from", "note")}
    out = []
    for w in row["waters"]:
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"{aid}-{key(w)}", event_type="beach_advisory",
            status="advisory_active", waterbody_text=w, started_at=day, time_precision="day", published_at=day,
            reported_at=day, authority=AUTHORITY, advice_text=advice_of(w, county, cause), source_url=row["url"],
            raw={"state": "KS", "time_zone": zones.kansas_zone(county=county), "title": safe_text(row.get("title")),
                 "description": row.get("description"), "release": aid, "waters": [w], "release_waters": list(row["waters"]), "county": county,
                 "cause": cause, "advisory_extent": "named_water", "advisory_noun": row.get("noun") or "Stream advisory",
                 "_placement": "named_water_only", "hand_entry": hand,
                 "start_basis": (f"KDHE's release, read by hand on {row['entered']}: the day KDHE published it "
                                 "(no time of day is given; it may have begun earlier)"),
                 "time_basis": "the release's publication day as indexed; KDHE's release page answers 403"}))
    return out


def apply_hand(rows: list[dict], recs: dict, at: str) -> int:
    """Hand-entered releases: a record not on file is added; a rescission entered in the row lifts it at that day
    (day precision); the records otherwise keep whatever a feed rescission did to them. Returns the open count."""
    n = 0
    for row in rows:
        for r in hand_records(row):
            cur = recs.setdefault(r["event_id"], r)
            if cur is not r:
                cur["raw"]["hand_entry"] = r["raw"]["hand_entry"]
            lift = row.get("rescission")
            if lift and cur["status"] == "advisory_active":
                cur.update(status="advisory_lifted", ended_at=lift["date"])
                cur["raw"].update(ended_at_precision="day", lifted_by={"title": lift.get("title"),
                                  "link": lift.get("url"), "date": lift["date"], "entered_by_hand": True})
            n += cur["status"] == "advisory_active"
    return n


def run(feed: bytes, prev: list[dict], at: str, hand: list[dict] | None = None) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    for r in recs.values():
        migrate(r)
    split_reopened(recs)
    stats = {"releases": 0, "issues": 0, "rescissions": 0, "lifted": 0, "rescissions_without_issue": 0,
             "revised_out": 0, "rescissions_ambiguous": 0, "regional_issues": 0}
    stats["hand_entered_open"] = apply_hand(hand or [], recs, at)
    its = items(feed)
    stats["releases"] = len(its)
    lifts, orphan, ambiguous = [], [], []
    present: set[str] = set()           # the issuing releases this read holds (re-review P1-4)
    for it in its:
        if kind(it["title"])[0] and iso(it["date"]) is None:
            # an issue or rescission without a usable publication time cannot be dated: the run fails with the
            # earlier records kept, never an advisory with no start or a lift with no time (verification P2-5)
            raise ValueError(f"KDHE stream advisory release {it.get('link')} has no usable publication time")
    for it in its:
        # every rescission this read holds, reconciled against the saved records before any observed period is
        # opened, so a water named again in the same read as its rescission never reopens (verification 3 P1-1)
        k, waters, county = kind(it["title"])
        if k == "lift":
            stats["rescissions"] += 1
            lifts.append((it, waters + desc_waters(it["description"]), county))
    unread = [it["title"] for it in its if not kind(it["title"])[0] and re.search(r"\badvisor", it["title"], re.I)
              and not NOT_STREAM.search(it["title"])]
    apply_lifts(lifts, recs, None, [], [])
    regional_lifts = [it for it in its if kind(it["title"])[0] == "regional_lift"]
    for it in sorted(its, key=lambda x: iso(x["date"]) or ""):
        k, waters, county = kind(it["title"])
        if k == "regional":
            stats["issues"] += 1
            stats["regional_issues"] += 1
            r = regional_record(it)
            present.add(r["raw"]["release"])
            if r["event_id"] in recs:
                old = recs[r["event_id"]]
                old["raw"].update(counties=r["raw"]["counties"], cause=r["raw"]["cause"])
                old["advice_text"] = r["advice_text"]
            else:
                recs[r["event_id"]] = r
            continue
        if k == "issue":
            stats["issues"] += 1
            now = issue_records(it, waters, county)
            aid = now[0]["raw"]["release"]
            present.add(aid)
            ids = set()
            for r in now:
                chain = sorted((x for x in recs.values() if base_of(x) == r["event_id"]),
                               key=lambda x: x["raw"].get("period") or 1)
                if not chain:
                    recs[r["event_id"]] = r
                    ids.add(r["event_id"])
                    continue
                last = chain[-1]
                if last["status"] == "advisory_lifted" and last["raw"].get("revised_out") \
                        and not rescinded(last) and not rescinded_now(r, lifts, recs):
                    # named again after a read that dropped it: a new observed period, never the old one reopened
                    nxt = reopened(last, r, at, len(chain) + 1)
                    recs[nxt["event_id"]] = nxt
                    ids.add(nxt["event_id"])
                else:
                    revise(last, r)
                    ids.add(last["event_id"])
            for r in recs.values():
                # a water the release no longer names (KDHE revised it): its advisory ends at this read, at poll
                # precision, never left open beside the water the release now names
                if r["raw"].get("release") == aid and r["event_id"] not in ids and r["status"] == "advisory_active":
                    r.update(status="advisory_lifted", ended_at=at)
                    r["raw"].update(ended_at_precision="poll", revised_out=True, end_basis=REVISED_OUT_BASIS)
                    stats["revised_out"] += 1
    apply_lifts(lifts, recs, stats, orphan, ambiguous)
    for it in regional_lifts:
        # a regional rescission lifts the open regional advisories issued before it (KDHE has issued one at a time)
        stats["rescissions"] += 1
        when = iso(it["date"])
        hit = [r for r in recs.values() if r["raw"].get("advisory_extent") == "regional"
               and r["status"] == "advisory_active" and when and iso_utc(r["started_at"]) <= iso_utc(when)]
        for r in hit:
            r.update(status="advisory_lifted", ended_at=when)
            r["raw"].update(ended_at_precision="minute", lifted_by={"title": it["title"], "link": it["link"], "date": when})
            r["raw"].pop("confirmed_by", None)
            stats["lifted"] += 1
        if not hit:
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
        elif r["status"] == "advisory_active" and r["raw"].get("hand_entry"):
            # entered by hand from KDHE's release: kept until a rescission is read, never aged out with the feed
            r["raw"]["_last_seen_in_source"] = at
            r["raw"]["confirmed_by"] = (f"entered by hand from KDHE's release of {r['raw']['hand_entry']['published']}; "
                                        f"KDHE's news flash feed read at {at} holds no rescission of it")
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    stats["rescissions_seen_without_issue"] = orphan
    stats["rescissions_seen_ambiguous"] = ambiguous
    stats["unread_advisory_titles"] = [safe_text(t) for t in unread]
    return out, stats


def safe_feed(body: bytes) -> bytes:
    """Only the stream advisory releases, never the rest of KDHE's news (Astra 2026-11-14 P1-9)."""
    keep = []
    for i in items(body):
        k, waters, county = kind(i["title"])
        if not k:
            continue
        if k.startswith("regional"):
            keep.append({"title": safe_text(i["title"]), "link": i["link"], "date": i["date"], "description": i["description"], "kind": k,
                         "counties": counties_of(f"{i['title']} {i['description']}"),
                         "cause": cause_of(f"{i['title']} {i['description']}")})
            continue
        # the facts read, never the release's description (re-review P1-9)
        keep.append({"title": safe_text(i["title"]), "link": i["link"], "date": i["date"], "description": i["description"], "kind": k,
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
        recs, stats = run(feed, prev, now_iso(), hand_rows())
    except (requests.RequestException, OSError, ET.ParseError, ValueError, KeyError, TypeError, IndexError) as e:
        write_events(SOURCE_ID, [], ok=False, error=error_detail(e))
        print(f"{SOURCE_ID}: {error_detail(e)}", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": FEED, **stats,
        "credit": "Kansas Department of Health and Environment, news flash",
        "caveat": ("KDHE's stream advisories as its news feed carries them: about a month of releases, with the release "
                   "pages closed to automated reading, so an advisory issued before this site began reading the feed "
                   "is shown only where it was entered from KDHE's release by hand: on November 15, 2026, the stream "
                   "and lake advisory KDHE issued on June 25, 2026 for Ladder Creek and Scott Lake in Scott County."),
        "cadence": "every refresh"})
    print(f"{SOURCE_ID}: {len(recs)} records ({ {k: v for k, v in stats.items() if not isinstance(v, list)} }) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
