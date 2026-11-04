"""Virginia Department of Health recreational water and swimming advisories -> data/build/events/va-vdh-advisories.json.

Source
  VDH's newsroom is WordPress; its search feeds are RSS with the full release in content:encoded:
  https://www.vdh.virginia.gov/news/?s=recreational+water+advisory&feed=rss2 (and &paged=N), plus the
  same feed for ?s=swimming+advisory, ?s=advisory+lifted (lift releases that do not say
  "recreational water") and ?s=sewage (older sewage advisories: Potomac River 2026, McClure River
  2026, Hoskins Creek and Gravelly Run 2025). Fish consumption, shellfish and drinking-water
  advisories are not recreational water advisories and are skipped. Ten releases per page; no key; no licence stated (public government
  news). Releases name media contacts and quote officials: those lines never leave this module.
  The raw pages are saved as the parsed items (title, link, pubDate, categories, release text
  without the contact block, quotes, emails, phones or WordPress user names), not as the XML.

Record rules
  - One advisory event per issued release; a later "lifted" release about the same place closes it
    (status advisory_lifted, ended_at = the lift's publication time, the "valid until"). A partial
    lift ("Partially Lifts Potomac River ...") is kept in raw and the advisory stays active; a
    second lift of an advisory already lifted (Bailey Bay was lifted twice on 2026-07-23) is kept in
    raw as a repeat. A lift whose issue is not in the feed is kept as its own record with started_at
    null (it sets no colour). Pairing: the place words of the titles (district names, "Issued",
    "Lifted", "Recreational Water Advisory" ... removed) must match or one must contain the other,
    with a distinctive word in common, the issue earlier and open, within 120 days; swimming
    (beach bacteria) advisories pair only with swimming advisories.
  - event_type: a swimming advisory (beach bacteria sampling) -> beach_advisory; a recreational
    water advisory after sewage -> sso, or bypass when the release names a treatment plant
    (power failure or loss of disinfection at a plant); algae -> hab_advisory; otherwise unknown
    (review). started_at = the issue's publication time (published_at the same); times are the
    RSS pubDate (UTC) shown in America/New_York; source_updated_at = the latest release of the pair.
  - waterbody_text = the affected stretch as the release words it ("Potomac River: The advisory
    area extends for 72.5 miles from ..."), else the place in the title; water slugs by name within
    Virginia (ingest/va_waters.py), water_match "name".
  - advice_text = the release's own advice sentences (avoid ..., may continue with proper caution,
    the beach sign wording); never written here.
  - Weekdays: VDH text sometimes pairs a weekday with the wrong date ("Tuesday, July 22" in 2026,
    a Wednesday; "Friday April 14" in 2026, a Tuesday). The dates are kept as published and each
    inconsistency is noted in raw.notes; nothing is corrected.
  - Every release seen is kept in data/build/va-vdh-advisories-state.json (the feeds page back only
    so far), so a pair survives when its issue drops off the first pages.

Run from pipeline/: python -m ingest.va_vdh_advisories [--backfill]   (backfill pages back to 2025-01-01)
Cadence: hourly.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, BUILD_DIR, event, now_iso, parse_volume_gal, read_json, save_raw,
                    scrub_text, write_events, write_json)
from ingest import va_waters
from ingest.nh_vt_waters import norm
from ingest.va_deq_prep import load_dischargers, operators_named, scrub_free

SOURCE_ID = "va-vdh-advisories"
FEED = "https://www.vdh.virginia.gov/news/"
QUERIES = ("recreational water advisory", "swimming advisory", "advisory lifted", "sewage")
STATE_PATH = BUILD_DIR / "va-vdh-advisories-state.json"
TZ = ZoneInfo("America/New_York")
BACKFILL_FROM = date(2025, 1, 1)
PAGES = 3
MAX_PAGES = 40
PAIR_DAYS = 120
REPEAT_DAYS = 3
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
TITLE_STOP = {"vdh", "issues", "issued", "issue", "lifts", "lifted", "lift", "lifting", "partially", "partly",
              "recreational", "water", "swimming", "advisory", "advisories", "for", "at", "in", "the", "of", "on",
              "following", "due", "to", "a", "an", "and", "sewage", "discharge", "sewer", "main", "break",
              "spill", "va", "virginia", "remains", "effect", "expanded", "extended", "update", "updated"}
GENERIC = {"beach", "beaches", "river", "creek", "bay", "run", "south", "north", "east", "west", "four", "three",
           "two", "public", "park", "point", "lake", "branch", "fork"}
DISTRICT = re.compile(r"^\s*(?:[\w.'’-]+\s+){1,3}health (?:district|department)\s+", re.I)
CONTACT_LINE = re.compile(r"^\s*(media|repair|press|pio)?\s*contacts?\s*:", re.I)


# ---------------------------------------------------------------- feed parsing

def _text(h: str) -> str:
    h = re.sub(r"(?i)</p>|<br\s*/?>|</li>|</h\d>|</div>", "\n", h or "")
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = htmllib.unescape(h).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in h.split("\n")]
    out = []
    for x in lines:
        if x == "-" or not x:
            continue
        if out and out[-1] == "-":
            out[-1] = "- " + x
        else:
            out.append(x)
    return "\n".join(out)


def clean_body(text: str, title: str) -> str:
    """Release text without the contact block, the WordPress footer, emails, phones and quotes."""
    lines = text.split("\n")
    t = norm(title)
    head_end = next((i for i, x in enumerate(lines[:12]) if norm(x) == t), None)
    out = []
    for i, x in enumerate(lines):
        if head_end is not None and 0 < i < head_end:
            continue                      # between the date line and the repeated title: contacts
        if CONTACT_LINE.match(x) or re.match(r"^\s*The post .* appeared first on", x) or x.strip("# ") == "":
            continue
        if re.search(r"\bsaid\b|\bsays\b|\baccording to\b", x, re.I):   # quotes name the speaker: not kept
            x = " ".join(s for s in re.split(r"(?<=[.!?”\"])\s+", x)
                         if not re.search(r"\bsaid\b|\bsays\b|\baccording to\b", s, re.I))
            if not x.strip():
                continue
        x = scrub_free(scrub_text(x))
        if "removed]" in x or re.search(r"(?i)interview requests|media inquiries|RSVP", x):
            # a contact sentence: it names a person
            x = " ".join(s for s in re.split(r"(?<=[.!?])\s+", x)
                         if "removed]" not in s and not re.search(r"(?i)interview requests|media inquiries|RSVP", s))
            if not x.strip(" -"):
                continue
        out.append(x)
    return "\n".join(out)


TOPIC_CATEGORY = re.compile(r"(?i)health (district|department)|beach|river|creek|\bbay\b|lake|\brun\b|park|point|"
                            r"reservoir|harbor|island|advisor|sewage|sewer|spill|water|alga|bloom|swimming")
TITLE_WORDS = re.compile(r"(?i)\b(manager|director|officer|specialist|coordinator|supervisor|pio|commissioner|"
                         r"spokes|epidemiologist|dr\.?)\b")


def keep_categories(cats) -> list[str]:
    """WordPress tags name places, topics and sometimes staff ('Mary ...', 'Environmental Health Manager
    ...'): only topic and place tags are kept."""
    return [c for c in cats if c and TOPIC_CATEGORY.search(c) and not TITLE_WORDS.search(c)]


def parse_feed(xml: str) -> list[dict]:
    items = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", it, re.S)
            v = m.group(1) if m else None
            if v and v.startswith("<![CDATA["):
                v = v[9:-3]
            return htmllib.unescape(v).strip() if v is not None else None
        title = re.sub(r"\s+", " ", tag("title") or "").strip()
        content = re.search(r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", it, re.S)
        cats = keep_categories(htmllib.unescape(c).strip() for c in re.findall(r"<category><!\[CDATA\[(.*?)\]\]></category>", it))
        pub = tag("pubDate")
        keep = action_of(title) != "other"      # not an advisory: its text is not kept
        items.append({"title": title, "link": tag("link"), "pubDate": pub,
                      "published": iso_local(pub), "categories": cats if keep else [],
                      "text": clean_body(_text(content.group(1) if content else ""), title) if keep else ""})
    return items


def iso_local(pub: str | None) -> str | None:
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub).astimezone(TZ).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- reading a release

def action_of(title: str) -> str:
    t = title.lower()
    if not re.search(r"advisor", t) or re.search(r"fish consumption|shellfish|drinking water|boil water|air quality|heat", t):
        return "other"
    if re.search(r"partial(ly)?\s+lift|partly\s+lift", t):
        return "partial_lift"
    if re.search(r"\blift(s|ed|ing)?\b|\bwithdrawn\b|\brescind", t):
        return "lifted"
    if re.search(r"\bissu(e|es|ed|ing)\b|\bexpand|\bextend", t):
        return "issued"
    return "other"


def kind_of(title: str) -> str:
    t = title.lower()
    return "swimming" if re.search(r"swimming advisor", t) and "recreational" not in t else "recreational"


PLURAL = {"beaches": "beach", "rivers": "river", "creeks": "creek", "bays": "bay", "parks": "park"}


def subject_tokens(title: str) -> set[str]:
    """Place words of a title: no district, action or advisory words, no 'due to ...' and no trailing
    'in <Town>' (a town alone never pairs two releases)."""
    t = DISTRICT.sub("", title)
    t = re.sub(r"(?i)\bdue to\b.*$", "", t)
    t = re.sub(r"\s+in\s+[A-Z][\w .’'-]*?(?:,\s*(?:VA|Va\.?|Virginia))?\s*$", "", t.strip())
    return {PLURAL.get(w, w) for w in norm(t).split() if w not in TITLE_STOP and len(w) > 1}


def subject_text(title: str) -> str:
    t = DISTRICT.sub("", title)
    t = re.sub(r"(?i)\b(vdh\s+)?(issues|issued|lifts|lifted|partially lifts|partially lifted)\b", " ", t)
    t = re.sub(r"(?i)\b(recreational( swimming| water)?|swimming) advisor(y|ies)\b", " ", t)
    t = re.sub(r"(?i)\bdue to\b.*$|\bfollowing\b.*$", "", t)
    t = re.sub(r"(?i)^\s*(for|at|in)\s+(the\s+)?|\s+(for|at)\s+(the\s+)?", " ", t)
    return re.sub(r"\s+", " ", t).strip(" ,-")


def lead(text: str) -> list[str]:
    """Paragraphs before the first bullet list (the release itself, not the standard advice)."""
    out = []
    for x in text.split("\n")[1:]:
        if x.startswith("- "):
            break
        out.append(x)
    return out


def sentences(paras: list[str]) -> list[str]:
    out = []
    for p in paras:
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", p) if s.strip()]
    return out


AREA_RE = re.compile(r"advisory (?:area|extent)|advisory (?:extends|covers|includes|applies|remains in place)|"
                     r"\bextending\b|\bfrom .{3,80}? to (?:the )?.{3,80}|throughout", re.I)
ADVICE_RE = re.compile(r"\bavoid\b|not advised|may continue with proper caution|advis(?:es|ing) (?:that )?(?:people|the public|residents)", re.I)


def area_of(text: str) -> str | None:
    for s in sentences(lead(text)):
        if AREA_RE.search(s) and re.search(r"advis", s, re.I):
            return s
    return None


def advice_of(text: str) -> str | None:
    picked = [s for s in sentences(lead(text)) if ADVICE_RE.search(s) and not re.search(r"\bsaid\b", s)]
    if not picked:
        sign = re.search(r"The signs? reads?:?\s*(.+)", text)
        if sign:
            picked = [sign.group(1)]
    if not picked:
        bullets = [x[2:] for x in text.split("\n") if x.startswith("- ")]
        picked = bullets[:1]
    return " ".join(picked[:3]) or None


def dateline_town(text: str) -> str | None:
    m = re.search(r"^([A-Z][A-Z .'-]{2,40}),\s*Va\.", text, re.M)
    return m.group(1).title() if m else None


def cause_type(title: str, text: str) -> tuple[str, str]:
    body = " ".join(lead(text)[:6])
    both = f"{title} {body}"
    if kind_of(title) == "swimming":
        return "beach_advisory", "swimming advisory from beach bacteria sampling"
    if re.search(r"algae|algal|cyanobacteria|bloom", both, re.I) and not re.search(r"sewage|sewer", both, re.I):
        return "hab_advisory", "the release names an algal bloom"
    if re.search(r"sewage|sewer|overflow|wastewater|force main", both, re.I):
        if re.search(r"(wastewater )?treatment (plant|facility)|\bWWTP\b|loss of (chlorination|disinfection)|"
                     r"disinfection|chlorination", body, re.I):
            return "bypass", "the release names a discharge from a treatment plant"
        return "sso", "the release names a sewage spill or sewer break"
    return "unknown", "no cause named in the release"


def weekday_notes(text: str, published: str | None) -> list[str]:
    if not published:
        return []
    pub = datetime.fromisoformat(published)
    notes = []
    rx = re.compile(rf"\b({'|'.join(WEEKDAYS)}),?\s+({'|'.join(MONTHS)})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*(\d{{4}}))?")
    for m in rx.finditer(text):
        wd, mon, day, yr = m.group(1), MONTHS.index(m.group(2)) + 1, int(m.group(3)), m.group(4)
        year = int(yr) if yr else (pub.year - 1 if mon - pub.month > 6 else pub.year)
        try:
            actual = WEEKDAYS[date(year, mon, day).weekday()]
        except ValueError:
            notes.append(f"The release says '{m.group(0)}', which is not a date; kept as published.")
            continue
        if actual != wd:
            notes.append(f"The release says '{m.group(0)}', but {m.group(2)} {day}, {year} is a {actual}; "
                         "the date is kept as published (not corrected).")
    return notes


def volume_of(texts: list[str]) -> tuple[int | None, str | None, str]:
    for t in texts:
        m = re.search(r"((?:approximately |about |an estimated |estimated )?\d[\d,.]*\s*(?:million |thousand )?gallons)", t, re.I)
        if m:
            gal, flag = parse_volume_gal(m.group(1))
            return gal, m.group(1), flag
    return None, None, "unknown"


# ---------------------------------------------------------------- pairing

def _compatible(a: set[str], b: set[str]) -> bool:
    common = a & b
    return bool(common - GENERIC) and (a <= b or b <= a or len(common) / max(1, len(a | b)) >= 0.6)


def pair(releases: list[dict]) -> list[dict]:
    """Advisories: [{issue, lift, partial: [...], repeats: [...]}] from releases sorted by time. A lift
    closes the open advisory it matches best; a lift whose place words cover several open advisories
    ("Lifted at Hilton and Huntington Beach") closes all of them."""
    rels = sorted((r for r in releases if r.get("published") and r["action"] != "other"), key=lambda r: r["published"])
    advisories: list[dict] = []
    for r in rels:
        toks, kind, t = r["tokens"], r["kind"], datetime.fromisoformat(r["published"])
        if r["action"] == "issued":
            advisories.append({"issue": r, "lift": None, "partial": [], "repeats": [], "tokens": toks, "kind": kind})
            continue
        open_, recent = [], []
        for a in advisories:
            first = a["issue"] or a["lift"] or a["partial"][0]
            t0 = datetime.fromisoformat(first["published"])
            if a["kind"] != kind or t0 > t or t - t0 > timedelta(days=PAIR_DAYS) or not _compatible(toks, a["tokens"]):
                continue
            if a["lift"] is None and a["issue"] is not None:
                open_.append(a)
            elif a["lift"] is not None and t - datetime.fromisoformat(a["lift"]["published"]) <= timedelta(days=REPEAT_DAYS):
                recent.append(a)
        if r["action"] == "partial_lift":
            if open_:
                max(open_, key=lambda a: (int(toks == a["tokens"]), a["issue"]["published"]))["partial"].append(r)
            else:
                advisories.append({"issue": None, "lift": None, "partial": [r], "repeats": [], "tokens": toks, "kind": kind})
            continue
        covered = [a for a in open_ if (a["tokens"] - GENERIC) and (a["tokens"] - GENERIC) <= toks]
        targets = covered if len(covered) > 1 else (
            [max(open_, key=lambda a: (int(toks == a["tokens"]), a["issue"]["published"]))] if open_ else [])
        if targets:
            for a in targets:
                a["lift"] = r
        elif recent:
            recent[-1]["repeats"].append(r)
        else:
            advisories.append({"issue": None, "lift": r, "partial": [], "repeats": [], "tokens": toks, "kind": kind})
    return advisories


def _release_raw(r: dict) -> dict:
    return {"title": r["title"], "link": r["link"], "pubDate": r["pubDate"], "published": r["published"],
            "action": r["action"], "categories": [c for c in r.get("categories") or [] if not re.search(r"@", c)],
            "dateline": dateline_town(r["text"]), "lead": lead(r["text"])[:8], "advisory_area": area_of(r["text"]),
            "advice": advice_of(r["text"])}


def _slug(link: str | None) -> str:
    parts = [p for p in (link or "").rstrip("/").split("/") if p]
    return parts[-1] if parts else "unknown"


def to_record(a: dict, refs: tuple, fetched_at: str) -> dict:
    issue, lift = a["issue"], a["lift"]
    main = issue or lift or (a["partial"][0] if a["partial"] else None)
    all_rels = [x for x in [issue, *a["partial"], lift, *a["repeats"]] if x]
    title, text = main["title"], main["text"]
    etype, basis = cause_type(title, "\n".join(x["text"] for x in all_rels))
    subject = subject_text(title)
    area = area_of(issue["text"]) if issue else None
    if not area:
        area = next((area_of(x["text"]) for x in all_rels if area_of(x["text"])), None)
    waterbody_text = f"{subject}: {area}" if area and subject and norm(subject) not in norm(area) else (area or subject or None)
    town = next((dateline_town(x["text"]) for x in all_rels if dateline_town(x["text"])), None)
    slugs, wnotes = va_waters.match_waters(f"{subject}. {area or ''}", [town] if town else None)
    notes = []
    for x in all_rels:
        notes += [f"{x['title']}: {n}" for n in weekday_notes(x["text"], x["published"])]
    notes = list(dict.fromkeys(notes))
    if issue and not lift:
        age = (datetime.fromisoformat(fetched_at.replace("Z", "+00:00")) - datetime.fromisoformat(issue["published"])).days
        if age > 60:
            notes.append(f"no lift release found in the feeds {age} days after the issue; kept as published (active)")
    if issue is None:
        notes.append("the issued release is not in the feed; this lift has no start")
    if lift and a["tokens"] != subject_tokens(lift["title"]):
        notes.append("the lift names the place differently from the issue (paired by the words in common)")
    vol, vtext, vflag = volume_of([" ".join(lead(x["text"])) for x in reversed(all_rels)])
    district = next((c for x in all_rels for c in x.get("categories") or [] if re.search(r"health (district|department)", c, re.I)), None)
    named = operators_named(" ".join(" ".join(lead(x["text"])) for x in all_rels)) if etype in ("sso", "bypass") else []
    did = named[0] if len(named) == 1 else None
    dname = (refs[1].get(did) or {}).get("name") if did else None
    status = "advisory_lifted" if lift else "advisory_active"
    started = issue["published"] if issue else None
    latest = max(x["published"] for x in all_rels)
    raw = {"releases": [_release_raw(x) | {"role": role} for role, xs in
                        (("issued", [issue] if issue else []), ("partial_lift", a["partial"]),
                         ("lifted", [lift] if lift else []), ("repeat_lift", a["repeats"])) for x in xs],
           "kind": a["kind"], "place_words": sorted(a["tokens"]), "event_type_basis": basis,
           "valid_until": lift["published"] if lift else None,
           "notes": notes or None, "water_placement": {"subject": subject, "town": town, "notes": wnotes or None},
           "discharger_named": named or None,
           "_time_basis": "RSS pubDate (UTC) shown in America/New_York; started_at = the issued release, ended_at = the lift"}
    return event(
        source_id=SOURCE_ID, source_record_id=_slug((issue or main)["link"]), event_type=etype, status=status,
        discharger_id=did, discharger_name=dname,
        waterbody_text=waterbody_text, water_slugs=slugs, water_match="name" if slugs else "none",
        started_at=started, ended_at=lift["published"] if lift else None, time_precision="minute",
        reported_at=None, published_at=started, source_updated_at=latest, fetched_at=fetched_at,
        material="sewage" if etype in ("sso", "bypass") else None, volume_gal=vol, volume_text=vtext,
        estimate_flag=vflag if vtext else "unknown",
        authority="Virginia Department of Health" + (f" ({district})" if district else ""),
        advice_text=advice_of(issue["text"]) if issue else advice_of(text),
        advice_window_hours=None, advice_window_basis=None,
        source_url=(issue or main)["link"], raw=raw,
        parse_error=None if etype != "unknown" else "no cause or kind recognised in the release (review)",
    )


# ---------------------------------------------------------------- main

def fetch_pages(sess, query: str, until: date | None, max_pages: int, state: dict, errors: list) -> int:
    n = 0
    for page in range(1, max_pages + 1):
        try:
            r = sess.get(FEED, params={"s": query, "feed": "rss2", "paged": page}, timeout=60)
            if r.status_code == 404:
                break                                   # WordPress: past the last page
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{query} p{page}: {type(e).__name__}: {e}")
            break
        items = parse_feed(r.text)
        save_raw(SOURCE_ID, json.dumps({"url": r.url, "items": items}, ensure_ascii=False, indent=0),
                 f"{norm(query).replace(' ', '-')}-{page}.json")
        for it in items:
            if it["link"]:
                if action_of(it["title"]) == "other":
                    it = {**it, "text": ""}     # not an advisory: its text is not kept
                state.setdefault("releases", {})[it["link"]] = it
                n += 1
        oldest = min((it["published"] for it in items if it["published"]), default=None)
        if not items or (until and oldest and oldest[:10] < until.isoformat()):
            break
        time.sleep(1)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="page back to 2025-01-01")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_PATH, {}) or {}
    sess = requests.Session()
    sess.headers.update({**BROWSER_HEADERS, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"})
    errors, seen = [], 0
    for q in QUERIES:
        seen += fetch_pages(sess, q, BACKFILL_FROM if args.backfill else None,
                            MAX_PAGES if args.backfill else PAGES, state, errors)
    if not seen:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(errors) or "no releases")
        print(f"{SOURCE_ID}: FAILED {errors}", file=sys.stderr)
        return 1
    state["last_poll_at"] = fetched_at
    write_json(STATE_PATH, state)
    releases = []
    for link, it in state["releases"].items():
        it["categories"] = keep_categories(it.get("categories") or [])
        releases.append({**it, "action": action_of(it["title"]), "kind": kind_of(it["title"]),
                         "tokens": subject_tokens(it["title"])})
    refs = load_dischargers()
    advisories = pair(releases)
    records = [to_record(a, refs, fetched_at) for a in advisories]
    ids = Counter(r["event_id"] for r in records)
    for r in records:
        if ids[r["event_id"]] > 1 and r["started_at"] is None:
            r["event_id"] += "-lift"
            r["source_record_id"] += "-lift"
    records.sort(key=lambda r: r.get("started_at") or r.get("source_updated_at") or "", reverse=True)
    c = Counter((r["event_type"], r["status"]) for r in records)
    meta = {"feeds": [f"{FEED}?s={q.replace(' ', '+')}&feed=rss2" for q in QUERIES], "releases_known": len(releases),
            "releases_not_advisories": sum(1 for x in releases if x["action"] == "other"),
            "advisories": len(records), "by_type_status": {f"{k[0]}/{k[1]}": v for k, v in c.items()},
            "errors": errors or None, "registry_ids": ["va-vdh-news-advisory-feed"],
            "timezone_note": "RSS pubDate is UTC; times are shown in America/New_York",
            "statewide": True}
    path = write_events(SOURCE_ID, records, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"{SOURCE_ID}: {len(releases)} releases, {len(records)} advisories {dict(c)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
