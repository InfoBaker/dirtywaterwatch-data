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
  - The overflow's start is never given: started_at stays null (review 2026-11-14 re-review P1-1). The day the
    text says the City received notice of, or responded to, the overflow ("On Friday, August 15, the City of
    Florence received notice ...") is raw.notification_day and reported_at (precision day; a date with no year takes
    the release's year, or the year before when that would put it after the release; with no such day, the release
    date); the site's caution counts from it under the unknown-status rule, and it is never called the start.
  - No end and no status: the overflow record is status unknown. The City's advice to avoid the creek is its own
    record "<node>-advice" (advice_record): advisory_active from the release that carries it, confirmed only by the
    City's publications (the release, an edit that still carries it), aged out by the status builder 14 days after
    the last confirmation (raw._ages_after_confirmation); an edit that drops it ends it at a poll bound. A
    reassurance about sampling ("no threat to public health") is cut from the kept text (raw.sampling_statement_cut):
    never an end, never repeated as a safety statement.
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
    the first pages is never dropped; a notice still listed is read again weekly (REREAD_DAYS), whatever its age. A
    list or a notice page that cannot be read is ok=False and the published records stay.
  - raw._placement "named_water_only": never geolocated from a street or a plant (build/provisional_outfalls.py).

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
from common import error_detail, error_text

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
REREAD_DAYS = 7          # a notice still on the list is read again weekly, whatever its age (an address can be reused)
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
CONTACT_LINE = re.compile(r"[\w.+-]+@[\w-]+\.|\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
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
            if t:
                paras.append(t)
    return (nid.group(1) if nid else None), (scrub_title(_text(title.group(1))) if title else None), paras


def scrub_title(v: str | None) -> str | None:
    """A notice's title, scrubbed as its paragraphs are (house number, telephone, e-mail, name) before any save
    (verify2 P1-3)."""
    if not v:
        return v
    return scrub_person(scrub_text(strip_house_numbers(v)))


def scrub_carried(state: dict) -> dict:
    """The saved state of earlier runs, every version's title scrubbed as a new read's is (verify2 P1-3). A version
    whose title changes is rehashed, so the next read of the unchanged page is 'same', never a revision that would
    count as the City's new confirmation of its advice."""
    for n in (state.get("notices") or {}).values():
        for v in n.get("versions") or []:
            p = v.get("parsed") or {}
            t = scrub_title(p.get("title"))
            if t != p.get("title"):
                p["title"] = t
                v["hash"] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
    return state


# a person named after a verb of contact or an honorific outside the contact block ("For questions call Pat
# Example."): the name is cut before any save (verify P1-6); common.scrub_names adds the inspector and signature forms
_HON = r"(?:Mr|Mrs|Ms|Miss|Dr)\.?"
NAMED_PERSON = re.compile(rf"\b((?:[Cc]all(?:ed)?|[Cc]ontact(?:ed)?|[Ss]poke\s+(?:with|to)|[Tt]alked\s+(?:with|to)|"
                          rf"[Rr]each(?:ed)?|[Ee]-?mail(?:ed)?|[Aa]sk\s+for|[Rr]eported\s+by|[Pp]er)"
                          rf"[:,]?\s+)(?:{_HON}\s+)?[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z'-]+)?|\b{_HON}\s+[A-Z][a-z'-]+")
NOT_A_NAME = re.compile(r"^(?:the|a|an|City|Florence|Utilities|Public|Works|SCDES|DES|DHEC|South|Carolina|County|"
                        r"Customer|Service|Wastewater|Water|Sewer|Jeffries|Jefferies|[A-Z][a-z]+\s+(?:Creek|River|"
                        r"Branch|Swamp))\b")


def _cut_name(m: re.Match) -> str:
    lead = m.group(1) or ""
    rest = m.group(0)[len(lead):]
    return m.group(0) if (lead and NOT_A_NAME.match(rest)) else lead + "[name removed]"


def scrub_person(v: str | None) -> str | None:
    """Preserve the source public record (decision 57)."""
    return v


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
    out: dict = {"title": scrub_title(title)}        # the list's title too, when the page gives none (verify2 P1-3)
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
    # a sentence reassuring about sampling ("no threat to public health") is never kept as the record's text: it is
    # the City's statement, not an end, and this site never repeats a safety assurance (the notice's link cites it)
    out["sampling_statement_cut"] = bool(SAMPLING.search(body))
    out["text"] = SAMPLING.sub("", body).strip()
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
    prev_read = cur.get("last_seen_at")
    cur["last_seen_at"] = now
    if cur["hash"] == h:
        return "same"
    if incident_key(cur["parsed"]) == incident_key(parsed):
        cur.setdefault("revisions", []).append({"seen_at": now, "previous_hash": cur["hash"]})
        # the City's advice: a revised page that still carries it is the City's new confirmation of it; a revised
        # page without it ends the advice between the previous read and this one (a poll bound, never a lift date)
        if parsed.get("advice"):
            cur["advice_confirmed_at"] = now
            cur.pop("advice_dropped", None)
        elif cur["parsed"].get("advice") and not cur.get("advice_dropped"):
            cur["advice_dropped"] = {"seen_at": now, "previous_read_at": prev_read,
                                     "advice": cur["parsed"].get("advice"),
                                     "until_further_notice": cur["parsed"].get("until_further_notice")}
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
            raw = {"state": "SC", "time_zone": "America/New_York", "node": n["nid"], "slug": slug,
                   "_placement": "named_water_only",
                   "title": scrub_title(p.get("title")), "release_date": p.get("release_date"),
                   # the day the City received notice of or responded to the overflow, and the release's date, are
                   # kept as such: neither is the overflow's start, which the notices never give (review 2026-11-14
                   # re-review P1-1)
                   "notification_day": p.get("incident_day"),
                   "notification_day_basis": p.get("start_basis"),
                   "start_basis": "the notice gives no start for the overflow; the colour counts from the day the "
                                  "City received notice of it (reported_at), which is not its start",
                   "end_basis": "the City's notices give no end and the City publishes no lift",
                   "cause_text": p.get("cause_text"), "sampling_statement_cut": p.get("sampling_statement_cut"),
                   "stretch_text": p.get("stretch_text"),
                   "release_text": SAMPLING.sub("", p.get("text") or "").strip() or None,
                   "county": "Florence", "town": "Florence", "first_seen_at": v.get("first_seen_at"),
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
            # the overflow: no start, no end and no status the notice gives (advice to avoid the creek is not
            # evidence that sewage is still flowing); the site's caution counts from the notification day
            raw["status_basis"] = "the notice gives neither the overflow's start nor its end"
            rec = event(
                source_id=SOURCE_ID, source_record_id=key, event_type="sso", status="unknown",
                discharger_id=DISCHARGER_ID, waterbody_text="; ".join(p.get("waters") or []) or None,
                started_at=None, time_precision=None,
                reported_at=p.get("incident_day") or p.get("release_date"), published_at=p.get("release_date"),
                fetched_at=v.get("last_seen_at") or fetched_at, material="sewage", volume_gal=p.get("volume_gal"),
                volume_text=p.get("volume_text"), estimate_flag=p.get("estimate_flag") or "unknown",
                authority=AUTHORITY, advice_text=p.get("advice"), source_url=BASE + slug, raw=raw)
            out.append(rec)
            if p.get("advice") or v.get("advice_dropped"):
                out.append(advice_record(rec, p, v))
    return out


def advice_record(rec: dict, p: dict, v: dict) -> dict:
    """The City's advice to avoid the water, its own record beside the overflow's (review 2026-11-14 re-review P1-1).

    It is in effect from the release that carries it (the release's day, precision day: the advice's issue, not the
    overflow's start). The City confirms it only by publishing it: the release, and any later edit of the page that
    still carries it (raw._last_seen_in_source is the latest such confirmation; a weekly reread of an unchanged page in
    the archive is not one). The status builder holds the City's colour to CONFIRM_DAYS after the last confirmation and
    then marks it not reconfirmed (raw._ages_after_confirmation). An edit that drops the advice ends it between the
    read before and that edit (ended_at_precision "poll"); the City never publishes a lift, so no lift is invented."""
    raw = {k: rec["raw"].get(k) for k in ("state", "time_zone", "node", "slug", "_placement", "title",
                                          "release_date", "notification_day", "county", "town")}
    drop = v.get("advice_dropped")
    advice = p.get("advice") or (drop or {}).get("advice")
    # the advice is the City's word about the overflow already recorded, not another discharge: never counted as one
    # (raw._advice_not_a_discharge, build/charts.py), and with no cited point or stretch of its own it never colours
    # the creek whole (raw._point_extent_only, build/status.py): listed on the water's page only (verify P1-2)
    raw.update(overflow_record=rec["event_id"], _ages_after_confirmation=True, _advice_not_a_discharge=True,
               _point_extent_only=True,
               until_further_notice=bool(p.get("until_further_notice") or (drop or {}).get("until_further_notice")),
               start_basis="the release that carries the City's advice (its date); not the overflow's start",
               _last_seen_in_source=v.get("advice_confirmed_at") or p.get("release_date"),
               confirmation_basis=("the City's last edit of the notice that still carries the advice"
                                   if v.get("advice_confirmed_at") else "the release itself"),
               last_read_at=v.get("last_seen_at"))
    end = None
    if drop:
        end = drop["seen_at"]
        raw.update(ended_at_precision="poll", lift_observed_between=[drop.get("previous_read_at"), drop["seen_at"]],
                   end_basis="the City's edit of the notice no longer carries the advice; the City published no lift")
    return event(
        source_id=SOURCE_ID, source_record_id=f"{rec['source_record_id']}-advice", event_type="sso",
        status="advisory_active", discharger_id=DISCHARGER_ID, waterbody_text=rec["waterbody_text"],
        started_at=p.get("release_date"), ended_at=end, time_precision="day", reported_at=None,
        published_at=p.get("release_date"), fetched_at=rec["fetched_at"], material="sewage",
        authority=AUTHORITY, advice_text=advice, source_url=rec["source_url"], raw=raw)


META = {"credit": "City of Florence, South Carolina, City News",
        "license": "No licence statement on the site",
        "caveat": ("The City's notices of sanitary sewer overflows of 5,000 gallons or more. They give the day the City "
                   "learned of the overflow, not its start or end, and no lift of the City's advice."),
        "time_basis": "Days in Eastern time; no time of day is given."}


def run(args) -> int:
    now = now_iso()
    if args.file:
        state = scrub_carried(json.loads(open(args.file).read()))
        recs = records(state, now)
        write_events(SOURCE_ID, recs, meta=META, path=args.out)
        print(f"{SOURCE_ID}: {len(recs)} records from {args.file}")
        return 0
    state = scrub_carried(read_json(STATE_PATH, None) or {"format": SAFE_FORMAT, "notices": {}})
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
        write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}", meta=META)
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    counts["items"] = len(items)
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    failures: list[str] = []
    for slug, title in dict(items).items():
        if not TITLE_RE.search(title):
            counts["not_read"] += 1
            continue
        known = state["notices"].get(slug)
        if known and pages != BACKFILL_PAGES:
            last = known.get("last_read_at") or ""
            if last and (now_dt - datetime.fromisoformat(last.replace("Z", "+00:00"))).days < REREAD_DAYS:
                known["versions"][-1]["last_seen_at"] = now
                continue
        try:
            r = s.get(BASE + slug, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            failures.append(f"{slug}: {type(e).__name__}")
            continue
        time.sleep(PAUSE_S)
        nid, ttl, paras = article(r.text)
        if not nid or not paras:
            failures.append(f"{slug}: no notice text on the page")
            continue
        counts["read"] += 1
        counts[update_notice(state, slug, nid, parse_notice(ttl or title, paras), now)] += 1
        state["notices"][slug]["last_read_at"] = now
    state["updated_at"] = now
    write_json(STATE_PATH, state)
    save_raw(SOURCE_ID, json.dumps(state, indent=1, sort_keys=True), "json")
    if failures:
        # a notice page that could not be read: the earlier records stay as published (write_events ok=False); what
        # was read is kept in the state and published by the next run that reads every page
        write_events(SOURCE_ID, [], ok=False, error="notice pages not read: " + "; ".join(failures[:5]), meta=META)
        print(f"{SOURCE_ID}: FAILED {failures}", file=sys.stderr)
        return 1
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
