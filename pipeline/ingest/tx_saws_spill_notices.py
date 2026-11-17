"""San Antonio Water System (SAWS) sewer spill notices: the news posts SAWS publishes when a spill reaches the level
Texas law makes it tell the public, each with TCEQ's notice form attached (source id tx-saws-spill-notices).

Source
  https://www.saws.org/feed/ (WordPress RSS, the ten newest posts) and the site search's feed for "spill",
  https://www.saws.org/search/spill/feed/rss2/?paged=N (ten posts a page, newest first, each with its title, link,
  publication time with its offset, its WordPress id in the guid "?p=NNNN" and its full text in content:encoded). The
  hourly run reads the main feed and the first search page; `--backfill` reads the search pages until one answers 404.
  A spill post links a PDF: the release and TCEQ's "Notice of Spill from a Wastewater Facility" (30 TAC 319.303), with
  the facility and its TCEQ permit, the location, the estimated time and date, the estimated volume, the type, the area
  potentially affected, the suspected cause, the actions taken and the precautions. Read 2026-11-17: the search feed
  held 37 items on four pages, 23 of them posts about a sewer spill; the newest notice is of April 28, 2026 (Rosillo
  Creek). SAWS posts the spills that meet the notice threshold of 30 TAC 319.302 (100,000 gallons; 50,000 in a
  sensitive area), not every spill: TCEQ's table lists more large SAWS spills than SAWS posted.

Record rules
  - A post is a notice when its title or text reports a sewer spill or overflow that occurred (responding to, cleaning
    up, managing, "occurred"), or it links a TCEQ notice PDF. Essays, campaigns and yearly summaries ("Highs and lows of
    SSOs") are counted apart in meta.not_notices.
  - One record per post (source_record_id the WordPress post id). Times are Central (America/Chicago): the form's
    "estimated time and date of spill", minute precision with a clock time, day without; without a readable form, the
    date the release states ("Sunday evening", "today") is not used for a time and the record carries the post's day
    with day precision and raw.start_basis saying so. No end time: the form has none, and none is invented.
  - Volume as the form writes it: "Spill estimated >100,000 gallons" stays volume_text, with no figure (a bound).
  - Water: the form's "area potentially affected" when it names a water (Rosillo Creek, San Antonio River); an unnamed
    or intermittent creek names none and the record is listed with its city and county (raw.county Bexar), unplaced.
    raw._placement "named_water_only": never geocoded from the location.
  - advice_text: "Don't swim in affected area streams, ponds or lakes." only where the form shows that box marked and
    the marks can be read; SAWS states no window, so the site's caution applies by the existing rules. The releases'
    own judgements ("No adverse impacts are expected") are never kept.
  - One spill, one record: the same spill reaches TCEQ's open-data table (tx-tceq-sso-opendata) months later. A notice
    whose operator (SAWS), start day (within a day) and volume (consistent with its bound) meet a TCEQ row gets
    duplicate_of that row (ingest/tx_spill_notice_form.link_tceq), recomputed every run from the current TCEQ file.

Privacy: the release names a press contact and the form a "contact for further information" with a telephone number:
neither is read into a record (the form's contact field is dropped; the release text is never stored). The location
keeps the street and drops the house number. The post's text is read in memory; data/raw keeps the parsed safe fields
only. The feed's dc:creator is never read.

Failures: a feed that cannot be read (main feed or first search page) writes ok=False and keeps the earlier records; a
feed read with no spill post in it is a healthy run with no new record. A notice PDF that cannot be read leaves the
record built from the post (raw.notice_read false, day precision) and is tried again on the next run.

Run from pipeline/:  python -m ingest.tx_saws_spill_notices [--backfill] [--file feed.xml ...] [--pdf-text dir]
"""
from __future__ import annotations

import html
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import tx_spill_notice_form as F

SOURCE_ID = "tx-saws-spill-notices"
MAIN_FEED = "https://www.saws.org/feed/"
SEARCH_FEED = "https://www.saws.org/search/spill/feed/rss2/"
HOMEPAGE = "https://www.saws.org/"
AUTHORITY = "San Antonio Water System (news release and TCEQ spill notice)"
DISCHARGER_ID = "tx-san-antonio-water-system"
DISCHARGER = "San Antonio Water System"
PERMIT_PREFIX = "WQ0010137"          # SAWS's TCEQ wastewater permits (10137-008 Salado Creek, -033 Steven M Clouse ...)
NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
TZ = F.CENTRAL

SPILL_WORDS = re.compile(r"\bsewer\s+(?:spill|overflow)s?\b|\bsewage\s+spill|\bspill\b", re.I)
OCCURRED = re.compile(r"\b(?:spill|overflow)s?\b[^.]{0,80}\b(?:occurred|occurs)\b|\b(?:responding|responds?|responded)\s+to\s+"
                      r"(?:a|two|the)\s+(?:\w+\s+){0,2}(?:spill|overflow)|\b(?:clean(?:ing)?\s+up|clean-up\s+underway|managing)\b"
                      r"[^.]{0,40}\b(?:spill|overflow)|\btriggers?\s+(?:a\s+)?sewer\s+spill|\bcauses?\s+(?:a\s+)?sewer\s+spill|"
                      r"\bsewer\s+spill\s+occurs\b", re.I)
NOT_NOTICE = re.compile(r"highs and lows|truth:|survey says|don.t let|campaign|awareness|accolade|promotes|"
                        r"what.s a sanitary", re.I)
NOTICE_PDF = re.compile(r"href=\"(h?t?t?ps?://[^\"]+\.pdf)\"", re.I)


def items(body: bytes) -> list[dict]:
    root = ET.fromstring(body)
    out = []
    for it in root.iter("item"):
        c = it.find("content:encoded", NS)
        out.append({"title": html.unescape(it.findtext("title") or "").strip(),
                    "link": (it.findtext("link") or "").strip().split("?")[0],
                    "date": (it.findtext("pubDate") or "").strip(), "guid": (it.findtext("guid") or "").strip(),
                    "html": c.text if c is not None and c.text else ""})
    return out


def post_id(it: dict) -> str | None:
    m = re.search(r"[?&]p=(\d+)$", it.get("guid") or "")
    return m.group(1) if m else None


def post_text(h: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", h or ""))
    return re.sub(r"\s+", " ", t).strip()


def pdf_link(h: str) -> str | None:
    """The notice PDF the post links (the first PDF), its scheme repaired when the post cut it ("ps://...")."""
    for m in NOTICE_PDF.finditer(h or ""):
        u = m.group(1)
        if u.startswith("ps://"):
            u = "htt" + u
        elif u.startswith("s://"):
            u = "http" + u
        if re.match(r"https?://(?:www\.|apps\.)?saws\.org/", u, re.I):
            return u.replace("http://", "https://", 1)
    return None


def is_notice(it: dict) -> bool:
    title, text = it["title"], post_text(it["html"])
    if NOT_NOTICE.search(title):
        return False
    if not SPILL_WORDS.search(title + " " + text[:400]):
        return False
    return bool(OCCURRED.search(title + ". " + text[:600]) or
                (pdf_link(it["html"]) and re.search(r"TCEQ", text, re.I)))


def pub_dt(it: dict):
    try:
        return parsedate_to_datetime(it["date"]).astimezone(TZ)
    except (TypeError, ValueError, IndexError):
        return None


def safe_title(t: str) -> str:
    return common.scrub_text(F.street_place(t) or t)


def pdf_text(content: bytes) -> str:
    import pypdf                                     # pipeline/requirements.txt; imported here so tests run without it
    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def record(it: dict, form_text: str | None, at: str) -> dict:
    pid = post_id(it)
    pub = pub_dt(it)
    if pid is None or pub is None:
        raise ValueError(f"SAWS post {it.get('link')} has no post id or publication time")
    f = F.form_fields(form_text or "")
    facility, permit = F.facility_permit(f.get("facility"))
    started, precision, words = F.spill_time(f.get("time"), TZ, pub.date())
    raw = {"state": "TX", "county": "Bexar", "city": "San Antonio", "time_zone": "America/Chicago",
           "_placement": "named_water_only", "provenance": "operator", "title": safe_title(it["title"]),
           "notice_pdf": pdf_link(it["html"]), "notice_read": bool(f), "state_permit_prefix": PERMIT_PREFIX,
           "legal_basis": "30 TAC 319.302-319.303 (notice to local officials and the media within 24 hours)"}
    if f:
        raw.update(facility=facility, state_permit=permit, location=F.street_place(f.get("location")),
                   spill_time_as_written=words, area_as_written=f.get("area"), cause=f.get("cause"),
                   spill_type=f.get("type"))
        marked, swim = F.precautions(form_text or "")
        raw["precautions_marked"] = marked
        raw["precautions_read"] = marked is not None
    water = F.water_of(f.get("area")) if f else None
    gal, flag, vtext = F.volume(f.get("volume")) if f else (None, "unknown", None)
    if started:
        raw["start_basis"] = "the estimated time and date of the spill on TCEQ's notice form"
    else:
        started, precision = pub.date().isoformat(), "day"
        raw["start_basis"] = ("the post's publication day: the notice form could not be read; the spill began on or "
                              "before it")
        raw["start_is_upper_bound"] = True
    return event(
        source_id=SOURCE_ID, source_record_id=pid, event_type="sso", status="unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, outfall_name=raw.get("location"),
        waterbody_text=water, started_at=started, time_precision=precision,
        published_at=pub.isoformat(), fetched_at=at, material="domestic wastewater" if f else "wastewater",
        volume_gal=gal, volume_text=vtext, estimate_flag=flag, authority=AUTHORITY,
        advice_text=(swim if f and raw.get("precautions_read") else None),
        source_url=f"https://www.saws.org/?p={pid}", raw=raw)


def run(feeds: list[bytes], prev: list[dict], at: str, get_pdf) -> tuple[list[dict], dict]:
    """(records, stats). get_pdf(url) -> the PDF's text or None."""
    recs = {r["event_id"]: r for r in prev}
    stats = {"items": 0, "posts": 0, "notices": 0, "not_notices": 0, "forms_read": 0, "forms_unread": 0}
    seen = set()
    for body in feeds:
        for it in items(body):
            pid = post_id(it)
            if pid is None or pid in seen:           # pages ("?page_id=") are not news posts
                continue
            seen.add(pid)
            stats["posts"] += 1
            if not is_notice(it):
                stats["not_notices"] += 1
                continue
            stats["notices"] += 1
            old = recs.get(f"{SOURCE_ID}:{pid}")
            if old and (old.get("raw") or {}).get("notice_read"):
                old["fetched_at"] = at
                stats["forms_read"] += 1
                continue
            url = pdf_link(it["html"])
            text = get_pdf(url) if url else None
            r = record(it, text, at)
            stats["forms_read" if r["raw"]["notice_read"] else "forms_unread"] += 1
            r["raw"]["first_seen_at"] = (old or {}).get("raw", {}).get("first_seen_at") or at
            recs[r["event_id"]] = r
        stats["items"] += len(items(body))
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["duplicates_of_tceq"] = F.link_tceq(out, F.tceq_rows())
    return out, stats


def safe_feed(body: bytes) -> bytes:
    keep = [{"post_id": post_id(it), "title": safe_title(it["title"]), "date": it["date"], "notice_pdf": pdf_link(it["html"])}
            for it in items(body) if post_id(it) and is_notice(it)]
    return json.dumps({"items": keep}, ensure_ascii=False, indent=1).encode()


def fetch(backfill: bool) -> list[bytes]:
    out = [requests.get(MAIN_FEED, headers=HEADERS, timeout=(20, 120))]
    out[0].raise_for_status()
    for n in range(1, 40 if backfill else 2):
        r = requests.get(SEARCH_FEED, params={"paged": n} if n > 1 else None, headers=HEADERS, timeout=(20, 120))
        if r.status_code == 404 and n > 1:           # past the last page; a 404 on the first page is a failure
            break
        r.raise_for_status()
        out.append(r)
    bodies = [r.content for r in out]
    save_raw(SOURCE_ID, b"[" + b",".join(safe_feed(b) for b in bodies) + b"]", "json")
    return bodies


def fetch_pdf(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=(20, 120))
        r.raise_for_status()
        return pdf_text(r.content)
    except Exception as e:                            # noqa: BLE001 - an unreadable PDF leaves the post's own record
        print(f"{SOURCE_ID}: notice PDF not read ({url}: {type(e).__name__})", file=sys.stderr)
        return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    get_pdf = fetch_pdf
    if "--pdf-text" in argv:                          # saved form texts: <dir>/<pdf file name>.txt
        d = Path(argv[argv.index("--pdf-text") + 1])
        get_pdf = lambda u: (d / (u.rsplit("/", 1)[-1] + ".txt")).read_text() if (d / (u.rsplit("/", 1)[-1] + ".txt")).exists() else None  # noqa: E731
    try:
        if "--file" in argv:
            i = argv.index("--file") + 1
            files = []
            while i < len(argv) and not argv[i].startswith("--"):
                files.append(argv[i])
                i += 1
            feeds = [Path(a).read_bytes() for a in files]
        else:
            feeds = fetch("--backfill" in argv)
        recs, stats = run(feeds, prev, now_iso(), get_pdf)
    except (requests.RequestException, OSError, ET.ParseError, ValueError, KeyError, TypeError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: run not ok ({e})", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": HOMEPAGE, "feeds": [MAIN_FEED, SEARCH_FEED], **stats,
        "credit": "San Antonio Water System (news releases and TCEQ spill notices)",
        "caveat": ("SAWS posts the spills that meet the public-notice threshold of 30 TAC 319.302 (100,000 gallons; 50,000 "
                   "in a sensitive area), not every spill; the time and volume are SAWS's estimates on TCEQ's form."),
        "cadence": "every refresh (the main feed and the first search page); --backfill reads every search page"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
