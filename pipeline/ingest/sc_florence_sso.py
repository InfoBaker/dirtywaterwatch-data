"""City of Florence (South Carolina) sanitary sewer overflow notices -> data/build/events/sc-florence-sso-notices.json

Source
  https://www.cityofflorencesc.gov/city-news (registry sc-florence-sso-notices): the City's news list (Drupal, about
  ten items a page, 38 pages on 2026-11-14, 446 items), among them "Notification of Sanitary Sewer Overflow" releases,
  each its own page (/news/<slug>, node id in the page's body class). Five such notices on 2026-11-14 (nodes 1027,
  1064, 1844, 1929 and 1969: Jeffries Creek, one spelled "Jefferies"). The City publishes them "pursuant to the City of
  Florence's policy of public notification for sanitary sewer overflows" of 5,000 gallons or more, a policy it
  adopted when the state required collection systems to enact public notification programs in 2008; S.C. Code
  48-1-95(E) now requires public notice of a significant spill (5,000 gallons or more) within 24 hours of discovery,
  through no named channel.

Which items are read
  An item whose title names a sanitary sewer overflow, a sewer or wastewater overflow or a sewage spill (TITLE_RE) is
  read; every other item (road closures for sewer repairs, boil-water notices, the sewer moratorium) is not
  (meta.not_read).

Record rules (rules only; no model, no geocoding)
  - The page: the article body only. The "Media Contacts" heading and any sentence asking readers to contact a named
    person are cut before anything is kept (CUT); the rest goes through common.strip_house_numbers and
    common.scrub_text.
  - published_at: the release's own date ("For Immediate Release – October 14, 2025"), precision day. reported_at
    stays null.
  - started_at: the day the text says the City received notice of, or responded to, the overflow ("On Friday,
    August 15, the City of Florence received notice ...", "responded ... on Sunday, March 3"): precision day, the
    overflow having begun on or before it (raw.start_basis says so); a date with no year takes the release's year,
    or the year before when that would put it after the release. With no such day, the release date, the latest the
    overflow can have begun (raw.start_basis).
  - No end: the notices give none. When the City advises avoiding the creek "until further notice" the record is
    status ongoing with raw.status_basis (the City's advice stands; the City publishes no lift), else unknown. A
    reassurance about sampling is kept as text, never as an end.
  - Volume: "an estimated 115,200 gallons" is volume_gal (estimated); "more than 5,000 gallons" is volume_text only
    (a lower bound, not a measurement, and never a figure per manhole).
  - Water: "on/near <Name> Creek|River|Branch|Swamp" in the title or text (WATER_RE); "Jefferies Creek" is the City's
    other spelling of Jeffries Creek (ALIASES, raw.water_alias). The stretch "downstream of <place>" is
    raw.stretch_text (house numbers removed). No point: a street near a manhole is never geocoded.
  - Type sso; operator the City of Florence (discharger sc-florence), no permit (the collection system's
    overflow is not tied to the plant's permit).
  - A notice whose page is edited is read again. The page's address is reused only for the same overflow: when an
    edit changes the release date or the incident's day (a new overflow written over an old notice), the new text is
    a new record "<node>-v<n>" and the earlier record is kept as it was (raw.later_version), so a reused address never
    overwrites an earlier report. An edit that keeps both dates updates the record (raw._revisions).
  - History: the list's first pages are read each run and the earlier notices are carried, so a notice that leaves
    the first pages is never dropped. A list that cannot be read is ok=False and the records stay.

Privacy: the media-contact block (a staff member's name, telephone and e-mail) and any "please contact" sentence are
cut before the raw save; house numbers near manholes are removed. tests/test_ingest_sc.py proves a name, an e-mail,
a telephone number and a house number never reach a record.

Cadence: hourly with the refresh. Run from pipeline/: python -m ingest.sc_florence_sso [--file saved.json] [--pages N]
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import time
from datetime import date, datetime

import requests

from common import (BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, strip_house_numbers,
                    write_events, write_json)

SOURCE_ID = "sc-florence-sso-notices"
BASE = "https://www.cityofflorencesc.gov"
LIST_URL = BASE + "/city-news?page={}"
STATE_PATH = BUILD_DIR / "sc-florence-sso-state.json"
SAFE_FORMAT = "dww-sc-florence-safe/1"
AUTHORITY = "City of Florence, South Carolina (Utilities)"
DISCHARGER_ID = "sc-florence"
TIMEOUT = (60, 300)
PAUSE_S = 1.0
PAGES = 2
BACKFILL_PAGES = 45
RECHECK_DAYS = 30
TITLE_RE = re.compile(r"sanitary\s+sewer\s+overflow|sewer\s+overflow|wastewater\s+overflow|sewage\s+(?:spill|overflow|"
                      r"release|discharge)", re.I)
MONTHS = "january february march april may june july august september october november december".split()
_MON = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
RELEASE_RE = re.compile(rf"For\s+Immediate\s+Release\s*[–—-]\s*{_MON}\s+(\d{{1,2}}),?\s+(\d{{4}})", re.I)
_DAY = rf"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+{_MON}\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?"
START_RULES = [
    (re.compile(rf"\bOn\s+{_DAY},?\s+(?:the\s+)?City(?:\s+of\s+Florence)?\s+(?:received\s+notice|was\s+notified|"
                rf"responded|became\s+aware|discovered)", re.I),
     "the day the City received notice of the overflow: it began on or before this day"),
    (re.compile(rf"\b(?:responded|notified|received\s+notice)[^.]{{0,80}}?\bon\s+{_DAY}", re.I),
     "the day the City responded to or was notified of the overflow: it began on or before this day"),
    (re.compile(rf"\bOn\s+{_DAY}\b", re.I), "the first day the notice gives: the overflow began on or before this day"),
]
GALLONS = re.compile(r"(?P<more>more\s+than|over|at\s+least|in\s+excess\s+of|approximately|an\s+estimated|estimated|"
                     r"about)?\s*(?P<n>\d{1,3}(?:,\d{3})+|\d+)\s+gallons", re.I)
_W = r"((?:[A-Z][a-z]+\s){1,3}(?:Creek|River|Branch|Swamp|Canal|Lake|Pond))"
WATER_RE = [re.compile(r"\b(?:on|near|into|to|reach(?:ed)?|entered)\s+(?:the\s+)?" + _W),
            re.compile(r"\b(?:downstream|upstream)\s+of\s+[^.;]*?,?\s+on\s+(?:the\s+)?" + _W)]
STRETCH = re.compile(r"\b((?:particularly\s+)?(?:downstream|upstream)\s+of\s+[^.;]+?)(?:,\s+on\s+|\.)", re.I)
ALIASES = {"Jefferies Creek": "Jeffries Creek"}
ADVICE = re.compile(r"[^.]*\b(?:advised\s+to\s+avoid|Avoid\s+swimming|should\s+(?:also\s+)?be\s+kept\s+away|avoid\s+contact)"
                    r"[^.]*\.", re.I)
UNTIL_FURTHER = re.compile(r"until\s+further\s+notice", re.I)
CAUSE = re.compile(r"[^.]*\bcaused\s+by\b[^.]*\.", re.I)
SAMPLING = re.compile(r"[^.]*\b(?:sampl|test)\w*[^.]*\b(?:no\s+threat|safe|normal|acceptable|below)\b[^.]*\.", re.I)
# the media-contact block and contact sentences are cut before anything is kept
CUT = re.compile(r"^\s*(?:Media\s+Contacts?|Contacts?:|For\s+(?:further|more)\s+information|###)", re.I)
CONTACT_SENTENCE = re.compile(r"[^.]*\b(?:[Pp]lease\s+contact|[Cc]ontact\s+[A-Z][a-z]+\s+[A-Z][a-z]+|or\s+SCDES\s+at)\b[^.]*\.?")
DATELINE = re.compile(r"^\s*FLORENCE,\s*S\.?\s*C\.?\s*[–—-]", re.I)
CLOSING = re.compile(r"^\s*The\s+information\s+provided\s+is\s+pursuant", re.I)
POLICY = re.compile(r"[^.]*\b(?:policy|or\s+more)\b[^.]*\.", re.I)
YESTERDAY = re.compile(r"\b(?:responded|notified|received\s+notice)[^.]{0,60}?\byesterday\b", re.I)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def list_items(page: str) -> list[tuple[str, str]]:
    seen, out = set(), []
    for m in re.finditer(r'href="(/news/[^"#?]+)"[^>]*>(.*?)</a>', page, re.S):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), _text(m.group(2))))
    return out


def article(page: str) -> tuple[str | None, str | None, list[str]]:
    """(node id, title, the article's paragraphs with the contact block cut), from a notice page."""
    nid = re.search(r"page-node-(\d+)", page)
    title = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
    body = None
    for m in re.finditer(r'class="[^"]*field--name-body[^"]*"[^>]*>(.*?)</div>', page, re.S):
        if re.search(r"Immediate\s+Release|FLORENCE,\s+SC", m.group(1), re.I):
            body = m.group(1)
            break
    paras = []
    if body:
        blocks = [_text(b) for b in re.split(r"</(?:p|h\d)>|<br\s*/?>", body)]
        blocks = [b for b in blocks if b]
        start = next((i for i, b in enumerate(blocks) if DATELINE.match(b)), None)
        head = [b for b in blocks[:start] if RELEASE_RE.search(b)] if start is not None else []
        rest = blocks[start:] if start is not None else []
        for t in head + rest:
            if CLOSING.match(t):
                break
            if CUT.match(t):
                continue
            t = CONTACT_SENTENCE.sub("", t).strip()
            if t:
                paras.append(scrub_text(strip_house_numbers(t)))
    return (nid.group(1) if nid else None), (_text(title.group(1)) if title else None), paras


def _ymd(mon: str, d: str, y: str | None, release: date | None) -> date | None:
    try:
        m = MONTHS.index(mon.lower()) + 1
        if y:
            return date(int(y), m, int(d))
        if release is None:
            return None
        guess = date(release.year, m, int(d))
        return guess if guess <= release else date(release.year - 1, m, int(d))
    except ValueError:
        return None


def parse_notice(title: str | None, paras: list[str]) -> dict:
    text = " ".join(paras)
    out: dict = {"title": title}
    m = RELEASE_RE.search(text)
    release = _ymd(m.group(1), m.group(2), m.group(3), None) if m else None
    out["release_date"] = release.isoformat() if release else None
    # a street's compass letter ("W. Palmetto Street") is not a sentence's end
    body = re.sub(r"\b([NSEW])\.\s", r"\1 ", RELEASE_RE.sub("", text))
    out["incident_day"], out["start_basis"] = None, None
    if release and YESTERDAY.search(body):
        out["incident_day"] = date.fromordinal(release.toordinal() - 1).isoformat()
        out["start_basis"] = ("the day before the release, which the notice calls 'yesterday' (derived): the City "
                              "responded that day and the overflow began on or before it")
    for rx, basis in START_RULES if out["incident_day"] is None else []:
        mm = rx.search(body)
        if mm:
            d = _ymd(mm.group(1), mm.group(2), mm.group(3), release)
            if d:
                out["incident_day"], out["start_basis"] = d.isoformat(), basis
                break
    vols = [(g.group("more") or "", int(g.group("n").replace(",", ""))) for g in GALLONS.finditer(POLICY.sub("", body))]
    out["volume_gal"], out["volume_text"], out["estimate_flag"] = None, None, "unknown"
    if len(vols) == 1:
        more, n = vols[0]
        if re.match(r"more|over|at\s+least|in\s+excess", more, re.I):
            out["volume_text"] = f"{more.strip()} {n:,} gallons (the City's figure, a lower bound)"
        else:
            out["volume_gal"], out["estimate_flag"] = float(n), "estimated"
    elif vols:
        out["volume_text"] = "; ".join(f"{m.strip()} {n:,} gallons".strip() for m, n in vols)
    waters = []
    for rx in WATER_RE:
        for t in (title or "", body):
            for w in rx.findall(t):
                w = ALIASES.get(w.strip(), w.strip())
                if w not in waters:
                    waters.append(w)
    out["waters"] = waters
    out["aliases_seen"] = sorted({a for a in ALIASES if a in (title or "") + body})
    st = STRETCH.search(body)
    out["stretch_text"] = st.group(1).strip() if st else None
    out["advice"] = " ".join(a.strip() for a in ADVICE.findall(body)) or None
    out["until_further_notice"] = bool(UNTIL_FURTHER.search(out["advice"] or ""))
    c = CAUSE.search(body)
    out["cause_text"] = c.group(0).strip() if c else None
    s = SAMPLING.search(body)
    out["sampling_text"] = s.group(0).strip() if s else None
    out["text"] = body
    return out


def incident_key(p: dict) -> tuple:
    return (p.get("release_date"), p.get("incident_day"))


def update_notice(state: dict, slug: str, nid: str, parsed: dict, now: str) -> str:
    """Fold a read of a notice page into the state: 'new', 'same', 'revised' or 'new_version' (module docstring)."""
    n = state["notices"].setdefault(slug, {"slug": slug, "nid": nid, "versions": []})
    h = hashlib.sha256(json.dumps(parsed, sort_keys=True).encode()).hexdigest()[:16]
    vs = n["versions"]
    if not vs:
        vs.append({"parsed": parsed, "hash": h, "first_seen_at": now, "last_seen_at": now})
        return "new"
    cur = vs[-1]
    cur["last_seen_at"] = now
    if cur["hash"] == h:
        return "same"
    if incident_key(cur["parsed"]) == incident_key(parsed):
        cur.setdefault("revisions", []).append({"seen_at": now, "previous_hash": cur["hash"]})
        cur.update(parsed=parsed, hash=h)
        return "revised"
    cur["later_version_seen_at"] = now
    vs.append({"parsed": parsed, "hash": h, "first_seen_at": now, "last_seen_at": now})
    return "new_version"


def records(state: dict, fetched_at: str) -> list[dict]:
    out = []
    for slug, n in sorted(state["notices"].items()):
        for i, v in enumerate(n["versions"]):
            p = v["parsed"]
            key = n["nid"] if i == 0 else f"{n['nid']}-v{i + 1}"
            start = p.get("incident_day") or p.get("release_date")
            raw = {"state": "SC", "time_zone": "America/New_York", "node": n["nid"], "slug": slug,
                   "title": p.get("title"), "release_date": p.get("release_date"),
                   "start_basis": p.get("start_basis") or ("the release's date, the latest the overflow can have begun"
                                                            " (the notice gives no earlier day)"),
                   "end_basis": "the City's notices give no end and the City publishes no lift",
                   "cause_text": p.get("cause_text"), "sampling_text": p.get("sampling_text"),
                   "stretch_text": p.get("stretch_text"), "release_text": p.get("text"),
                   "county": "Florence", "first_seen_at": v.get("first_seen_at"),
                   "_last_seen_in_source": v.get("last_seen_at")}
            if p.get("aliases_seen"):
                raw["water_alias"] = {a: ALIASES[a] for a in p["aliases_seen"]}
            if v.get("revisions"):
                raw["_revisions"] = v["revisions"]
            if v.get("later_version_seen_at"):
                raw["later_version"] = {"seen_at": v["later_version_seen_at"],
                                        "note": "the City's page was later rewritten for another overflow; this record "
                                                "keeps the earlier text"}
            if i > 0:
                raw["earlier_version_of_page"] = n["nid"]
            status = "ongoing" if p.get("until_further_notice") else "unknown"
            if status == "ongoing":
                raw["status_basis"] = ("the City advises avoiding the creek until further notice and has published "
                                       "no lift")
            out.append(event(
                source_id=SOURCE_ID, source_record_id=key, event_type="sso", status=status,
                discharger_id=DISCHARGER_ID, waterbody_text="; ".join(p.get("waters") or []) or None,
                started_at=start, time_precision="day" if start else None, published_at=p.get("release_date"),
                fetched_at=v.get("last_seen_at") or fetched_at, material="sewage", volume_gal=p.get("volume_gal"),
                volume_text=p.get("volume_text"), estimate_flag=p.get("estimate_flag") or "unknown",
                authority=AUTHORITY, advice_text=p.get("advice"), source_url=BASE + slug, raw=raw))
    return out


META = {"credit": "City of Florence, South Carolina, City News",
        "license": "No licence statement on the site",
        "caveat": ("The City's notices of sanitary sewer overflows of 5,000 gallons or more. They give the day the City "
                   "learned of the overflow, not its start or end, and no lift of the City's advice."),
        "time_basis": "Days in Eastern time; no time of day is given."}


def run(args) -> int:
    now = now_iso()
    if args.file:
        state = json.loads(open(args.file).read())
        recs = records(state, now)
        write_events(SOURCE_ID, recs, meta=META, path=args.out)
        print(f"{SOURCE_ID}: {len(recs)} records from {args.file}")
        return 0
    state = read_json(STATE_PATH, None) or {"format": SAFE_FORMAT, "notices": {}}
    s = requests.Session()
    s.headers.update(HEADERS)
    pages = BACKFILL_PAGES if (args.backfill or not state.get("backfilled_at")) else args.pages
    counts = {"items": 0, "read": 0, "not_read": 0, "new": 0, "same": 0, "revised": 0, "new_version": 0}
    try:
        items = []
        for p in range(pages):
            r = s.get(LIST_URL.format(p), timeout=TIMEOUT)
            r.raise_for_status()
            got = list_items(r.text)
            if not got:
                if p == 0:
                    raise RuntimeError("the news list showed no items")
                break
            items += got
            time.sleep(PAUSE_S)
        if pages == BACKFILL_PAGES:
            state["backfilled_at"] = now
    except (requests.RequestException, RuntimeError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=META)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    counts["items"] = len(items)
    today = datetime.fromisoformat(now.replace("Z", "+00:00")).date()
    for slug, title in dict(items).items():
        if not TITLE_RE.search(title):
            counts["not_read"] += 1
            continue
        known = state["notices"].get(slug)
        if known:
            rel = known["versions"][-1]["parsed"].get("release_date")
            if rel and (today - date.fromisoformat(rel)).days > RECHECK_DAYS:
                known["versions"][-1]["last_seen_at"] = now
                continue
        try:
            r = s.get(BASE + slug, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"{SOURCE_ID}: {slug}: {e}", file=sys.stderr)
            continue
        time.sleep(PAUSE_S)
        nid, ttl, paras = article(r.text)
        if not nid or not paras:
            continue
        counts["read"] += 1
        counts[update_notice(state, slug, nid, parse_notice(ttl or title, paras), now)] += 1
    state["updated_at"] = now
    write_json(STATE_PATH, state)
    save_raw(SOURCE_ID, json.dumps(state, indent=1, sort_keys=True), "json")
    recs = records(state, now)
    write_events(SOURCE_ID, recs, meta={**META, "counts": counts})
    print(f"{SOURCE_ID}: {len(recs)} records; {counts}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved state (safe notices) to build from, no network")
    ap.add_argument("--out")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--pages", type=int, default=PAGES)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
