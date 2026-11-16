"""Nevada Office of State Epidemiology harmful algal bloom reports (the "Hot Topic: Harmful Algal Blooms" page).

Source
  https://nvose.org/hot-topic-harmful-algal-blooms/ (registry: nv-ose-hab-reports), Nevada Office of State
  Epidemiology. No key, no licence stated. A WordPress page with two accordions: "Active HAB Reports", one
  <details>/<summary> block per water ("Mountain View Pond, Gardnerville, NV", "Lake Mohave including Placer Cove, Eagle
  Wash, and Cottonwood Cove"), each with one or more paragraphs in the Office's words ("Wild Horse Reservoir has been
  placed on a HAB Watch advisory as of 8/13/2026 ...", "On 11/2/26 the Lahontan Reservoir advisory level has been
  lowered from a HAB Danger to a HAB Warning ..."), followed by two blocks that are not waters ("Tips and Information
  about HABs", "Dashboard"); then "Previous HAB Reports", one block per year with bold water names and no lift date
  (2026-11-16). The list is statewide: it carries the parks' waters and others (city ponds, Walker Lake, Lake Mohave).

Record rules
  - One hab_advisory record per advisory the active list states, the Office's own advisory, quoted as theirs: status
    advisory_active (red, the authority's window, while the Office lists it). The level is the Office's word: Watch,
    Warning and Danger as the state parks' feed records them (raw.level, raw.level_history); any other word is kept
    as the Office wrote it and shown as the site's caution (raw.code_undecoded, raw._caution_label), never dropped.
  - A paragraph whose subject is the block's water ("Walker Lake", "the Lahontan Reservoir", "Mountain View Pond in
    Gardnerville, NV") is an advisory for the whole named water (raw.advisory_extent "named_water", as Wyoming's and
    Colorado's). A subject naming places the block's heading lists as parts ("Eagle Wash and Placer Cove") gives one
    record per part (raw.advisory_extent "part_of_water", raw.part): it never colours the whole water. A subject that
    is neither leaves the block unread (below).
  - Times: started_at is the earliest date the Office states for that advisory on its first read ("as of 6/23/2026",
    "effective 09/30/2026", "On 11/2/26", and an earlier level the block names, "the 9/9/2026 HAB Danger"), the day as
    given (time_precision day, Pacific time; raw.start_basis); source_updated_at is the date of the current level. A
    level change later keeps the record and adds to raw.level_history. No end is invented: an advisory that a complete
    healthy read no longer lists ends at that read (advisory_lifted, raw.ended_at_precision poll, an upper bound),
    unless the Previous section states its lift affirmatively with a date ("Walker Lake's HAB advisory has been lifted
    as of 10/1/2026"; never "will be lifted"), which then is the end (precision day). An advisory listed again later is
    a new record (its key carries the first read's time, to the second).
  - Placement: no point is given and none is made. A water this site holds a record of (KNOWN: the exact name and
    the county that holds it) is placed by that name in that county only (raw._placement "named_water_only",
    raw.county; the status build's county-aware name placement). Any other water (Virginia Lake, Mountain View Pond,
    South Meadows Community Pond on 2026-11-16) is listed with the place the Office gives (raw.place) and placed on no
    water (raw._placement "listed_only"): a name is never guessed onto another county's or state's namesake.
  - One water, one listing (coordinator, 2026-11-16): where the state parks' feed (nv-state-parks-hab) carries the
    same whole water, active and read within PARKS_FRESH_H, this record (the Office's stated date) is the one shown:
    raw._shown_over names the parks' record, which the status build marks as this one's duplicate while both are
    active (status.shown_over_links); raw.also_cited and the authority name both publishers; the level shown is the
    stricter of the two (raw.level_basis, raw.office_level). Part-of-water records are never linked.
  - A bad read changes nothing: a failed request, a page missing either heading or its closing tag (truncated), a
    block count that does not match, or an active section with no water block and no explicit empty marker ("There
    are currently no active HABs") writes ok=False and keeps the earlier records. One water block that cannot be read
    (a paragraph about an advisory in another form, a date the reader cannot take or after the read, a subject that is
    neither the water nor a listed part) is listed in meta.unread with its reason; the readable blocks update, no
    earlier advisory is ended on that read (all are held, raw._held_unread), and health stays false until it is read.
    Advisory text or a heading outside the blocks fails the read (Astra review P1-2, P1-3).
  - A place the Office gives for a known water that does not name the county of its record ("Rye Patch Reservoir in
    Lincoln County") leaves the advisory listed only (Astra review P1-4). A duplicate link holds only while the parks'
    record is in the status build and active (build/status.py stale_links, P1-5).
  - Privacy: only the block headings and the advisory paragraphs are read (the help-line block is never read). Each
    paragraph is cleaned sentence by sentence before any save (the parks' rules: a sentence that can carry a person is
    withheld whole; "contact with water" is advice, not a contact); headings and names go through clean_field; the raw
    save is the cleaned items as JSON, never the markup; carried records are cleaned again on every save path.

Run from pipeline/:  python -m ingest.nv_ose_hab_list [--file saved.html]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, write_events
from ingest import nv_state_parks_hab as P
from zones import nevada_zone

SOURCE_ID = "nv-ose-hab-reports"
PARKS_SOURCE = "nv-state-parks-hab"
URL = "https://nvose.org/hot-topic-harmful-algal-blooms/"
AUTHORITY = "Nevada Office of State Epidemiology (HAB reports)"
LEVELS = P.LEVELS
PARKS_FRESH_H = 48
ZONE = ZoneInfo("America/Los_Angeles")

ACTIVE_H2 = re.compile(r"<h2\b[^>]*>\s*Active\s+HAB\s+Reports\s*</h2>", re.I)
PREVIOUS_H2 = re.compile(r"<h2\b[^>]*>\s*Previous\s+HAB\s+Reports\s*</h2>", re.I)
DETAILS = re.compile(r"<details\b[^>]*>\s*<summary\b[^>]*>(?P<summary>.*?)</summary>(?P<body>.*?)</details>", re.S | re.I)
NOT_WATERS = {"tips and information about habs", "dashboard"}
EMPTY = re.compile(r"\bno\s+active\s+(?:HABs?|harmful\s+algal\s+blooms?|HAB\s+(?:reports|advisories)|advisories)\b", re.I)
D = r"\d{1,2}/\d{1,2}/\d{2}(?:\d{2})?"
VERBS = r"placed\s+on|placed\s+under|downgraded\s+to|upgraded\s+to|raised\s+to|lowered\s+to|elevated\s+to|reduced\s+to|moved\s+to"
PLACED = re.compile(rf"^(?P<subject>[^.]+?)\s+(?:has|have)\s+been\s+(?:{VERBS})\s+an?\s+HAB\s+(?P<level>\w+)\s+advisory\s+"
                    rf"(?:as\s+of|effective|on)\s+(?P<date>{D})(?!\d)", re.I)
CHANGED = re.compile(rf"^On\s+(?P<date>{D}),?\s+the\s+(?P<subject>[^.]+?)\s+(?:HAB\s+)?advisory\s+level\s+(?:has\s+been|was)\s+"
                     rf"(?:lowered|raised|downgraded|upgraded|changed|elevated|reduced)\s+from\s+an?\s+HAB\s+(?P<from>\w+)\s+"
                     rf"to\s+an?\s+HAB\s+(?P<level>\w+)\b", re.I)
REFERENCE = re.compile(rf"^To\s+view\s+the\s+previous\b[^.]{{0,80}}?\bregarding\s+the\s+(?P<date>{D})\s+HAB\s+(?P<level>\w+)\b", re.I)
ADVISORY_WORDS = re.compile(r"\badvisor(?:y|ies)\b|\bHAB\s+(?:Watch|Warning|Danger)\b|\blift(?:ed|s)?\b", re.I)
LIFT = re.compile(rf"(?:On\s+(?P<d1>{D}),?\s+the\s+(?P<s1>[^.]+?)\s+(?:HAB\s+)?advisory\s+(?:has\s+been|was)\s+lifted"
                  rf"|(?P<s2>[A-Z][^.]*?)(?:'s)?\s+(?:HAB\s+)?advisory\s+(?:has\s+been|was)\s+lifted\s+(?:as\s+of|effective|on)\s+"
                  rf"(?P<d2>{D}))(?!\d)", re.I)
# "avoid contact with the water", "in contact with water": advice, not a person's contact; masked only for the check
BENIGN = re.compile(r"\bcontact\s+with\s+(?:the\s+)?water(?:body)?\b", re.I)
PART_SPLIT = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+", re.I)

# waters this site holds a record of, by the Office's exact name -> the county that holds the record's water. The parks'
# five come from the parks' feed (P.WATERS, each cited there); Walker Lake (walker-lake-nv, Mineral County) and Lake
# Mohave (lake-mohave-nv, Clark County, the Nevada side of the lake) are openboatlaunch records (data/waters-nv.json).
KNOWN = {**{k: v[0] for k, v in P.WATERS.items()}, "Walker Lake": "Mineral County", "Lake Mohave": "Clark County"}
START_BASIS = ("the earliest date the Office of State Epidemiology's list states for this advisory (its 'as of' or "
               "'effective' date, or the date of an earlier level it names), the day as given, Pacific time")
END_BASIS = ("the first read of the Office's list that no longer listed this advisory, an upper bound: the list gives no "
             "lift date")
STATED_END_BASIS = "the lift date the Office's list states for this advisory, the day as given, Pacific time"
LISTED_ONLY_NOTE = ("this site holds no record of this water: listed with the place the Office gives and placed on no "
                    "water, so it colours none")


def us_date(s: str) -> date:
    m, d, y = (int(x) for x in s.split("/"))
    return date(y + 2000 if y < 100 else y, m, d)


def clean_text(s: str) -> tuple[str, int]:
    """The parks' sentence cleaner (P.clean_text), with "contact with the water" read as advice, not a contact."""
    kept, withheld = [], 0
    for sent in re.split(r"(?<=[.!?])(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<!\bSt\.)\s+", s or ""):
        probe = BENIGN.sub(" ", sent)
        if P.PERSONAL_SENTENCE.search(probe) or P.HOUSE_NUMBER.search(probe):
            withheld += 1
            continue
        kept.append(P.COORD_IN_TEXT.sub(lambda m: f"{round(float(m.group(1)), 3):.3f}", sent))
    return scrub_text(" ".join(x for x in kept if x).strip()), withheld


def recleaned(p: dict) -> dict:
    """A carried record cleaned again before any save (P.recleaned), its advice text by this feed's cleaner."""
    out = P.recleaned(p)
    if isinstance(p.get("advice_text"), str):
        out["advice_text"] = clean_text(p["advice_text"])[0]
    return out


def heading_parts(summary: str) -> tuple[str, str | None, list[str]]:
    """(water, place, listed parts) of a block heading: "Lake Mohave including Placer Cove, Eagle Wash, and Cottonwood
    Cove" -> ("Lake Mohave", None, [the three]); "Mountain View Pond, Gardnerville, NV" -> (the pond, "Gardnerville, NV",
    [])."""
    m = re.match(r"^(.+?)\s+including\s+(.+)$", summary, re.I)
    if m:
        return m.group(1).strip(), None, [x for x in PART_SPLIT.split(m.group(2).strip()) if x]
    water, _, place = summary.partition(",")
    return water.strip(), place.strip() or None, []


def known_name(water: str) -> str | None:
    return next((k for k in KNOWN if k.casefold() == water.casefold()), None)


def read_block(summary: str, body: str, fetched_day: date) -> tuple[list[dict], dict | None]:
    """(advisory items, None) for a readable water block, or ([], {reason}) for one that cannot be read whole."""
    water, place, parts = heading_parts(summary)
    canon = known_name(water) or water
    items, earlier = [], []
    paras = [P.text_of(x) for x in re.split(r"</?p\b[^>]*>", body, flags=re.I)]
    for t in [x for x in paras if x]:
        m = PLACED.match(t) or CHANGED.match(t)
        r = None if m else REFERENCE.match(t)
        if r:
            earlier.append({"level": r.group("level").title(), "date": r.group("date")})
            continue
        if not m:
            if ADVISORY_WORDS.search(t):
                return [], {"reason": "a paragraph about an advisory in a form the reader does not take"}
            continue
        subject = re.sub(r"^the\s+", "", m.group("subject").strip(), flags=re.I)
        if subject.casefold() == water.casefold() or subject.casefold().startswith(water.casefold() + " in "):
            targets = [None]
            if subject.casefold().startswith(water.casefold() + " in "):
                place = place or subject[len(water) + 4:].strip()
        else:
            named = [x for x in PART_SPLIT.split(subject) if x]
            if not named or not all(x.casefold() in {p.casefold() for p in parts} for x in named):
                return [], {"reason": "an advisory for a place the block's heading does not name"}
            targets = named
        for part in targets:
            items.append({"water": canon, "part": part, "level_word": m.group("level"), "date": m.group("date"),
                          "from": m.groupdict().get("from"), "text": t})
    if not items:
        return [], {"reason": "no advisory statement read in the block"}
    for it in items + earlier:
        try:
            d = us_date(it["date"])
        except ValueError:
            return [], {"reason": "a date the reader cannot take"}
        if d > fetched_day + timedelta(days=1):
            return [], {"reason": "a date after the read"}
        it["date"] = d.isoformat()
    seen = [(it["water"], it["part"]) for it in items]
    if len(seen) != len(set(seen)):
        return [], {"reason": "one advisory stated twice in the block"}
    out = []
    for it in items:
        clean, withheld = clean_text(it["text"])
        level = it["level_word"].title()
        history = ([{"level": e["level"], "date": e["date"], "basis": "an earlier level the block names"}
                    for e in earlier] if it["part"] is None else [])
        if it.get("from"):
            history.append({"level": it["from"].title(), "basis": "the level the Office lowered or raised from"})
        start = min([it["date"]] + [e["date"] for e in history if e.get("date")])
        item = {"water": P.clean_field(it["water"]), "place": P.clean_field(place, "place") if place else None,
                "part": P.clean_field(it["part"], "place") if it["part"] else None, "level": level,
                "level_date": it["date"], "start": start, "stated_levels": history, "text": clean}
        if withheld:
            item["sentences_withheld"] = withheld
        out.append(item)
    return out, None


def parse(page: str, fetched: str | None = None) -> dict:
    """{items, unread, lifts, on_page}; ValueError for a page that is not a complete reading."""
    if not re.search(r"</html\s*>", page or "", re.I):
        raise ValueError("the page is not complete (no closing html tag)")
    a, b = list(ACTIVE_H2.finditer(page)), list(PREVIOUS_H2.finditer(page))
    if len(a) != 1 or len(b) != 1 or b[0].start() < a[0].end():
        raise ValueError("the page's 'Active HAB Reports' and 'Previous HAB Reports' headings are not as expected")
    active = page[a[0].end(): b[0].start()]
    blocks = list(DETAILS.finditer(active))
    if len(re.findall(r"<details\b", active, re.I)) != len(blocks) or \
            len(re.findall(r"</details>", active, re.I)) != len(blocks):
        raise ValueError("the active section's blocks are not completely readable")
    fetched_day = (datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZONE).date()
                   if fetched else date.today())
    waters = [m for m in blocks if P.text_of(m.group("summary")).casefold() not in NOT_WATERS]
    rest = DETAILS.sub(" ", active)
    outside = P.text_of(rest)
    # anything about an advisory, or a heading, outside a block read fails the read (Astra P1-2): a water written in
    # another wrapper would otherwise be lifted as absent
    if ADVISORY_WORDS.search(EMPTY.sub(" ", outside)) or re.search(r"<(?:h[1-6]|summary|strong|b)\b", rest, re.I):
        raise ValueError("advisory text or a heading stands outside the active section's blocks")
    if not waters and not EMPTY.search(outside):
        raise ValueError("the active section lists no water and does not say there are no active HABs")
    if waters and EMPTY.search(outside):
        raise ValueError("the active section says there are no active HABs beside listed waters")
    items, unread = [], []
    for m in waters:
        summary = P.text_of(m.group("summary"))
        water = heading_parts(summary)[0] if summary else ""
        got, bad = read_block(summary, m.group("body"), fetched_day) if summary else ([], {"reason": "a blank heading"})
        if bad:
            # the key is made from the cleaned name, never the raw heading (Astra P1-1)
            unread.append({"heading": P.clean_field(summary) if summary else "",
                           "block_key": P.slug(P.clean_field(known_name(water) or water)), **bad})
        items += got
    prev_text = P.text_of(page[b[0].end():])
    lifts = []
    for m in LIFT.finditer(prev_text):
        subj = re.sub(r"^the\s+", "", (m.group("s1") or m.group("s2") or "").strip(), flags=re.I)
        try:
            lifts.append({"subject": subj.casefold(), "date": us_date(m.group("d1") or m.group("d2")).isoformat()})
        except ValueError:
            continue
    return {"items": items, "unread": unread, "lifts": lifts, "on_page": len(waters)}


def saved_form(parsed: dict) -> str:
    """What the raw save keeps: the cleaned items and the unread headings, as JSON; never the page's markup."""
    return json.dumps({"url": URL, "items": parsed["items"], "unread": parsed["unread"]}, ensure_ascii=False, indent=1)


def key_of(it: dict) -> str:
    return P.slug(it["water"]) + (f"--{P.slug(it['part'])}" if it.get("part") else "")


def rank(level: str | None) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


def parks_active(parks: list[dict] | None, fetched: str) -> dict[str, dict]:
    """The parks' active records read within PARKS_FRESH_H of this read, by water key."""
    out = {}
    now = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    for p in parks or []:
        raw = p.get("raw") or {}
        seen = raw.get("_last_seen_in_source")
        if p.get("status") != "advisory_active" or not raw.get("water_key") or not seen:
            continue
        try:
            age = now - datetime.fromisoformat(str(seen).replace("Z", "+00:00"))
        except ValueError:
            continue
        if -timedelta(hours=1) <= age <= timedelta(hours=PARKS_FRESH_H):
            out[raw["water_key"]] = p
    return out


def build(page: str, fetched: str, previous: list[dict], parks: list[dict] | None = None) -> tuple[list[dict], dict]:
    parsed = parse(page, fetched)
    items, unread = parsed["items"], parsed["unread"]
    held_blocks = {u["block_key"] for u in unread}
    open_prev = {}
    for p in previous:
        raw = p.get("raw") or {}
        if p.get("status") == "advisory_active" and raw.get("water_key"):
            open_prev[raw["water_key"]] = p
    in_parks = parks_active(parks, fetched)
    records: dict[str, dict] = {}
    opened = duplicates = 0
    for it in items:
        k = key_of(it)
        prev = open_prev.get(k)
        praw = (prev or {}).get("raw") or {}
        srid = prev["source_record_id"] if prev else f"{k}:{P.episode_stamp(fetched)}"
        opened += prev is None
        history = list(praw.get("level_history") or [])
        if not history:
            history = [dict(h, seen_at=fetched) for h in it["stated_levels"]]
        if not history or history[-1].get("level") != it["level"] or history[-1].get("date") != it["level_date"]:
            history.append({"level": it["level"], "date": it["level_date"], "seen_at": fetched})
        part = it.get("part")
        county = KNOWN.get(it["water"])
        if county and it.get("place") and county.split()[0].casefold() not in it["place"].casefold():
            county = None       # a place the Office gives that does not name the record's county (Astra P1-4)
        raw = {"water_key": k, "block_key": P.slug(it["water"]), "water": it["water"], "part": part,
               "place": it.get("place"), "level": it["level"], "level_date": it["level_date"],
               "level_history": P.deep_clean(history), "advisory_extent": "part_of_water" if part else "named_water",
               "time_zone": nevada_zone(), "start_basis": START_BASIS,
               "_first_seen_at": praw.get("_first_seen_at") or fetched, "_last_seen_in_source": fetched,
               "page_url": URL, "state": "NV", "county": county}
        if it["level"] not in LEVELS:
            raw["code_undecoded"] = (f"the Office's level 'HAB {it['level']}' is not one of Watch, Warning or Danger: "
                                     "shown as the site's caution")
            raw["_caution_label"] = f"HAB {it['level']} (the Office's words): the site's caution"
        if county:
            raw["_placement"] = "named_water_only"
            raw["placement_hint"] = {"name": it["water"], "county": county, "state": "NV",
                                     "basis": "the water the Office's list names, in the county that holds its record"}
        else:
            raw["_placement"] = "listed_only"
            raw["placement_note"] = LISTED_ONLY_NOTE
        if it.get("sentences_withheld"):
            raw["sentences_withheld"] = it["sentences_withheld"]
        # both feeds on one water (coordinator, 2026-11-16): this record, which carries the Office's stated date, is
        # the one shown; the parks' record becomes its duplicate in the status build (status.shown_over_links), and
        # both publishers are cited. The level shown is the stricter of the two, never the weaker.
        authority, level_shown = AUTHORITY, it["level"]
        pk = in_parks.get(P.slug(it["water"])) if not part else None
        if pk:
            plevel = (pk.get("raw") or {}).get("level")
            raw["_shown_over"] = pk["event_id"]
            raw["also_cited"] = {"source_id": PARKS_SOURCE, "authority": pk.get("authority"),
                                 "source_url": pk.get("source_url"), "event_id": pk["event_id"], "level": plevel,
                                 "started_at": pk.get("started_at"), "time_precision": pk.get("time_precision")}
            authority = f"{AUTHORITY}; also listed by {pk.get('authority') or P.AUTHORITY}"
            if rank(plevel) > rank(it["level"]):
                level_shown = plevel
                raw["office_level"] = it["level"]
                raw["level"] = plevel
                raw["level_basis"] = (f"the stricter of the two: the parks' page lists HAB {plevel}, the Office's list "
                                      f"HAB {it['level']}")
                raw.pop("code_undecoded", None)
                raw.pop("_caution_label", None)
            else:
                raw["office_level"] = it["level"]
            duplicates += 1
        where = f" ({part}, {it['water']})" if part else ""
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory", status="advisory_active",
            waterbody_text=it["water"], lat=None, lon=None, coord_source=None, coord_precision_m=None,
            started_at=prev["started_at"] if prev else it["start"], time_precision="day",
            source_updated_at=it["level_date"], fetched_at=fetched, authority=authority,
            advice_text=f"HAB {level_shown} advisory (Nevada Office of State Epidemiology){where}: {it['text']}",
            source_url=URL, raw=raw)
    lifted = held = kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in records:
            continue
        p = recleaned(p)
        raw = dict(p.get("raw") or {})
        if p.get("status") == "advisory_active":
            if unread:          # a partial read ends nothing (Astra P1-3): every earlier advisory is held
                raw["_held_unread"] = ("the read was partial (" + ", ".join(sorted(held_blocks)) + " unread): held "
                                       "as it was")
                held += 1
            else:
                subj = (raw.get("part") or raw.get("water") or "").casefold()
                start_day = str(p.get("started_at") or "")[:10]
                today = datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZONE).date().isoformat()
                stated = [x["date"] for x in parsed["lifts"] if x["subject"] == subj and start_day <= x["date"] <= today]
                if stated:
                    p.update(status="advisory_lifted", ended_at=max(stated))
                    raw.update(ended_at_precision="day", end_basis=STATED_END_BASIS)
                else:
                    p.update(status="advisory_lifted", ended_at=fetched)
                    raw.update(ended_at_precision="poll", end_basis=END_BASIS, _unlisted_since=fetched)
                lifted += 1
        p["raw"] = raw
        records[sid] = p
        kept += 1
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "on_page": parsed["on_page"], "advisories_read": len(items),
            "by_level": {lv: sum(1 for it in items if it["level"] == lv) for lv in LEVELS},
            "other_levels": sorted({it["level"] for it in items if it["level"] not in LEVELS}),
            "listed_only": sorted({it["water"] for it in items if it["water"] not in KNOWN}),
            "unread": unread, "opened": opened, "lifted_this_read": lifted, "held_unread": held,
            "shown_over_parks": duplicates, "kept_from_previous": kept - lifted - held,
            "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "cadence": "page read every run; the Office updates it when an advisory changes, with no fixed schedule",
            "coverage": "Nevada statewide: every advisory the Office's active list states"}
    return out, meta


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        if "--file" in argv:
            page = Path(argv[argv.index("--file") + 1]).read_text(errors="replace")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(30, 120))
            r.raise_for_status()
            page = r.text
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        parks = (read_json(EVENTS_DIR / f"{PARKS_SOURCE}.json", {}) or {}).get("records", [])
        recs, meta = build(page, fetched, prev, parks)
        if "--file" not in argv:
            save_raw(SOURCE_ID, saved_form(parse(page, fetched)), "json")   # the cleaned items only, never the page
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        P.write_refused(SOURCE_ID, P.safe_error(e), EVENTS_DIR)
        print(f"{SOURCE_ID}: FAILED {P.safe_error(e)}", file=sys.stderr)
        return 1
    if meta["unread"]:
        why = "; ".join(f"{u['heading']}: {u['reason']}" for u in meta["unread"])
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error=f"unread blocks: {why}", meta=meta)
        print(f"{SOURCE_ID}: PARTIAL {len(meta['unread'])} block(s) unread -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['on_page']} waters on the list, {meta['advisories_read']} advisories {meta['by_level']}, "
          f"{len(recs)} records, {meta['advisory_active']} active, {meta['shown_over_parks']} shown over the parks' "
          f"records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
