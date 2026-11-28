"""RIDOH beach advisory feed (Rhode Island): the dated items at https://health.ri.gov/ridoh-feed-beaches.

Source
  https://health.ri.gov/ridoh-feed-beaches (registry: ri-ridoh-beach-advisory-feed), Rhode Island Department of
  Health. A Drupal list of dated items, newest first (25 a page; the whole 2026 season, 22 items, fit on the first
  page on 2026-11-16; "?page=1" returned the same items). Each item is a node (/node/<id>) with a title, a time to the
  second (shown to the minute) and RIDOH's text: "The Rhode Island Department of Health (RIDOH) recommends closing the
  swimming area at King Park Beach in Newport due to high bacteria counts." and, later, "... recommends re-opening the
  swimming area at ... because ...". Some items list the beaches in their own paragraphs ("the following beaches",
  "Sandy Point Beach, Portsmouth"). Season notices ("Beach Monitoring for 2026 Has Ended") state no advisory.
  The page answers the pipeline's runner (runner probe 43877571236, 2026-11-16).

What it adds to ingest.ri_ridoh_beaches (the Google Sheet behind health.ri.gov/beaches)
  The same closures: every closure the feed published in 2026 is a row of the sheet, closed on the same day. The
  feed gives the time RIDOH published each recommendation, to the minute, and the reason in RIDOH's words; the sheet
  gives days only and no reason. The feed is not complete: it carries no camp or cyanobacteria closures, and King
  Park Beach's re-opening (8/18 in the sheet) was never posted. Two re-openings were posted a day after the sheet's
  Re-Opened date (Hazards and Gooseberry Beach 6/27 08:33, sheet 6/26; Oakland and Conimicut Beach 8/7 10:06,
  sheet 8/6).

Record rules
  - One record per beach per closing item: beach_closure, or hab_advisory when the reason RIDOH gives names
    cyanobacteria or blue-green algae. status advisory_active (red, the authority's window) until a later item
    affirmatively recommends re-opening that beach ("recommends re-opening the swimming area(s) at ..."), which is the
    end (advisory_lifted). started_at and published_at are the closing item's publication time and ended_at the
    re-opening item's (time_precision minute, raw.ended_at_precision minute): RIDOH's recommendation is the advisory
    and runs from its publication. A closing item for a beach already closed is a new record; a re-opening ends every
    earlier open record of that beach and category (a bacteria re-opening never lifts a bloom advisory); a read with
    an unreadable item ends nothing. The season's end, an item that scrolls off the page, or a re-opening for a beach
    with no open record ends or invents nothing (meta.unmatched_reopenings).
  - Text: the beach as RIDOH names it (a shared "beach" in "Oakland and Conimicut beach" completed for each name, said
    so in raw.name_basis), the town RIDOH gives, the reason in RIDOH's words (raw.reason). The re-opening item's
    reason is not kept.
  - Placement: as ingest.ri_ridoh_beaches places the sheet's rows: RIDOH's own beach layer (RIDOHGIS_Beaches_View) by
    name and town, the point rounded to 0.001 degree, the water by its name or the only water near the point. A beach
    the layer does not hold is listed with its name and town and placed on no water (raw._placement listed_only).
  - One advisory, one listing: a record whose beach is the same RIDOH beach (layer BeachID) as a sheet record of the
    same type closed on the same local day is that record's duplicate (duplicate_of): the sheet's record is the one
    shown, as before, and this record keeps the feed's times and reason beside it (raw.same_as_sheet). A closure in
    the feed only is shown on its own.
  - A bad read changes nothing: a failed request, a page without its closing tag, the list's heading or container,
    no item, or an item count that does not match writes ok=False and keeps the earlier records. One item that cannot
    be read (an advisory in a form the reader does not take, a missing date) is listed in meta.unread; the readable
    items update, and health stays false until it is read.
  - Privacy: only an item's node, title, date and its recommendation paragraphs are read (the closing paragraph with
    RIDOH's telephone line is not). Every field is cleaned before any save; the raw save is the parsed items as JSON.

Run from pipeline/:  python -m ingest.ri_ridoh_beach_feed [--file saved.html]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import nv_state_parks_hab as P
from ingest import ri_ridoh_beaches as R
from ingest import ri_waters

SOURCE_ID = "ri-ridoh-beach-advisory-feed"
SHEET_SOURCE = R.SOURCE_ID
URL = "https://health.ri.gov/ridoh-feed-beaches"
NODE_URL = "https://health.ri.gov/node/{}"
AUTHORITY = R.AUTHORITY
ZONE = ZoneInfo("America/New_York")

CONTAINER = re.compile(r'<div\b[^>]*class="[^"]*\bview-ridoh-feed-beaches\b', re.I)
H1 = re.compile(r"<h1\b[^>]*>\s*Beach\s+Advisories\s*</h1>", re.I)
ARTICLE = re.compile(r"<article\b[^>]*>(?P<body>.*?)</article>", re.S | re.I)
NODE = re.compile(r'<h2\b[^>]*>\s*<a\s+href="/node/(?P<nid>\d+)"[^>]*>(?P<title>.*?)</a>\s*</h2>', re.S | re.I)
TIME = re.compile(r'<time\s+datetime="(?P<t>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)"', re.I)
LEAD = re.compile(r"^The Rhode Island Department of Health \(RIDOH\) recommends (?P<verb>closing|re-?opening) the "
                  r"swimming areas? (?:at )?(?P<rest>.+?)\s*$", re.I)
CLOSE_TAIL = re.compile(r"^(?P<list>.+?)\s+(?:due to|because of)\s+(?P<reason>[^.]+?)\.?$", re.I)
REOPEN_TAIL = re.compile(r"^(?P<list>.+?)\s+because\s+(?P<reason>[^.]+?)\.?$", re.I)
LIST_INTRO = re.compile(r"^(?:the following beaches|several beaches\b.*)$", re.I)
LIST_HEAD = re.compile(r"^Recommended swimming area closures:?$", re.I)
BOILERPLATE = re.compile(r"^RIDOH will continue\b", re.I)
SEASON = re.compile(r"\bbeach\s+monitoring\b", re.I)
ADVISORY_WORDS = re.compile(r"\b(?:recommend\w*|advisor(?:y|ies)|clos(?:e|ed|ing|ure|ures)|re-?open\w*)\b", re.I)
PLACE_WORD = re.compile(r"\b(?:beach|cove|pond|park|camp|campground|ymca|lake|area|reservoir)\b", re.I)
NAME_SHAPE = re.compile(r"^[A-Z][\w’'.&\- ]{1,60}$")
START_BASIS = ("the time RIDOH published its recommendation to close (the feed item's date, to the minute): the advisory "
               "runs from its publication")
END_BASIS = "the time RIDOH published its recommendation to re-open this beach (the feed item's date, to the minute)"
SAME_AS_SHEET = ("the same RIDOH beach (beach layer id) closed on the same local day in RIDOH's closure sheet "
                 "(ri-ridoh-beaches): that record is the one shown, this one keeps the feed's times and reason")
LISTED_ONLY_NOTE = ("a beach RIDOH's beach layer does not hold: listed with RIDOH's name and town and placed on no "
                    "water, so it colours none")


def text_of(fragment: str) -> str:
    return P.text_of(fragment).replace("\u00a0", " ").strip()


def split_beaches(s: str) -> list[dict] | None:
    """'Bristol Town Beach in Bristol, Sandy Point Beach in Portsmouth, and Georgiaville Pond Beach in Smithfield' ->
    three {name, town}; 'Oakland and Conimicut beach in Warwick' -> Oakland Beach and Conimicut Beach, Warwick (the
    shared word completed, name_basis); None when a part is not a beach name."""
    bits = re.split(r"(\s*,\s*(?:and\s+)?|\s+and\s+)", s.strip().rstrip("."))
    parts, joins = [x.strip() for x in bits[0::2]], [x.strip() for x in bits[1::2]]
    if any(not p for p in parts):
        return None
    out = []
    for p in parts:
        name, sep, town = p.rpartition(" in ")
        if not sep:
            name, town = p, None
        out.append({"name": name.strip(), "town": town.strip() if town else None})
    for i in range(len(out) - 2, -1, -1):
        # "Hazards and Gooseberry Beach in Newport", "Oakland Beach and Conimicut Beach in Warwick": a name joined by
        # "and" alone shares the town that follows; a comma never carries a town over
        if out[i]["town"] is None and out[i + 1]["town"] is not None and joins[i] == "and":
            out[i]["town"] = out[i + 1]["town"]
    last = out[-1]["name"] if out else ""
    m = re.search(r"\s(beach)$", last, re.I)
    for b in out:
        if not PLACE_WORD.search(b["name"]) and m:
            b["name"] = f"{b['name']} Beach"
            b["name_basis"] = "RIDOH's shared word 'beach' completed for this name"
        b["name"] = re.sub(r"\sbeach$", " Beach", b["name"])
        if not NAME_SHAPE.match(b["name"]) or (b["town"] is not None and not NAME_SHAPE.match(b["town"])):
            return None
    return out or None


def list_line(s: str) -> dict | None:
    """'Sandy Point Beach, Portsmouth' or 'Mackerel Cove Beach in Jamestown' -> {name, town}."""
    s = s.strip().rstrip(".")
    m = re.match(r"^(?P<name>.+?)(?:,\s*|\s+in\s+)(?P<town>[A-Z][\w .'-]+)$", s)
    if not m or not NAME_SHAPE.match(m.group("name")) or not PLACE_WORD.search(m.group("name")):
        return None
    return {"name": m.group("name").strip(), "town": m.group("town").strip()}


def read_item(body: str) -> tuple[dict | None, dict | None, bool]:
    """(item, None, False) for an advisory item, (None, {reason}, False) for one that cannot be read, (None, None, True)
    for a notice that states no advisory."""
    nm, tm = NODE.search(body), TIME.search(body)
    if not nm or not tm:
        return None, {"reason": "an item without its link or date"}, False
    title = text_of(nm.group("title"))
    paras = [text_of(x) for x in re.findall(r"<p\b[^>]*>(.*?)</p>", body, re.S | re.I)]
    paras = [x for x in paras if x]
    base = {"node": nm.group("nid"), "published_at": tm.group("t")}
    lead = next((i for i, x in enumerate(paras) if LEAD.match(x)), None)
    if lead is None:
        if ADVISORY_WORDS.search(title + " " + " ".join(paras)) and not (SEASON.search(title) and not re.search(
                r"\brecommend", title + " " + " ".join(paras), re.I)):
            return None, {**base, "reason": "an item about an advisory in a form the reader does not take"}, False
        return None, None, True
    m = LEAD.match(paras[lead])
    verb = "close" if m.group("verb").lower() == "closing" else "reopen"
    tail = (CLOSE_TAIL if verb == "close" else REOPEN_TAIL).match(m.group("rest"))
    if not tail:
        return None, {**base, "reason": "a recommendation whose beaches or reason cannot be read"}, False
    listed = tail.group("list").strip()
    if LIST_INTRO.match(listed):
        beaches = []
        for x in paras[lead + 1:]:
            if BOILERPLATE.match(x):
                break
            if LIST_HEAD.match(x):
                continue
            b = list_line(x)
            if b is None:
                return None, {**base, "reason": "a listed beach the reader cannot take"}, False
            beaches.append(b)
    else:
        beaches = split_beaches(re.sub(r"^the\s+", "", listed, flags=re.I)) or []
    if not beaches:
        return None, {**base, "reason": "a recommendation naming no beach the reader can take"}, False
    reason = P.clean_text(tail.group("reason").strip())[0] if verb == "close" else None
    # the category a re-opening speaks for, from its reason (never kept as text): bloom or bacteria (Astra P2-4)
    scope = ("hab_advisory" if R.HAB_RE.search(tail.group("reason")) else "beach_closure") if verb == "reopen" else None
    return {**base, "title": P.clean_field(title, "place"), "kind": verb, "reason": reason, "scope": scope,
            "beaches": [{k: (P.clean_field(v, "place") if isinstance(v, str) and k in ("name", "town") else v)
                         for k, v in b.items()} for b in beaches]}, None, False


def parse(page: str) -> dict:
    """{items, unread, notices, on_page}; ValueError for a page that is not a complete reading."""
    if not re.search(r"</html\s*>", page or "", re.I):
        raise ValueError("the page is not complete (no closing html tag)")
    c = CONTAINER.search(page)
    if not c or not H1.search(page[c.end():]):
        raise ValueError("the page's 'Beach Advisories' list is not as expected")
    rest = page[c.end():]
    arts = list(ARTICLE.finditer(rest))
    if not arts or len(re.findall(r"<article\b", rest, re.I)) != len(arts):
        raise ValueError("the list's items are not completely readable")
    items, unread, notices = [], [], 0
    for a in arts:
        it, bad, notice = read_item(a.group("body"))
        if it:
            items.append(it)
        elif bad:
            unread.append(bad)
        elif notice:
            notices += 1
    if len({i["node"] for i in items}) != len(items):
        raise ValueError("one item listed twice")
    return {"items": items, "unread": unread, "notices": notices, "on_page": len(arts)}


def saved_form(parsed: dict) -> str:
    """What the raw save keeps: the parsed items as JSON; never the page's markup."""
    return json.dumps(P.deep_clean({"url": URL, **parsed}), ensure_ascii=False, indent=1)


def local_day(t: str) -> str:
    return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(ZONE).date().isoformat()


def ident(name: str, town: str | None, beaches: list[dict]) -> tuple:
    cands, _ = R.match_beach(name, town or "", beaches)
    lat, _, _, used = R.place(cands)
    if lat is not None and used:
        return ("id", tuple(sorted(str(b["beach_id"]) for b in used)))
    return ("name", " ".join(R.tokens(R.clean_name(name))), ri_waters.norm_town(town) if town else "")


def same_beach(a: tuple, b: tuple) -> bool:
    if a[0] == "id" and b[0] == "id":
        return bool(set(a[1]) & set(b[1]))
    if a[0] == "name" and b[0] == "name":
        return a[1] == b[1] and (not a[2] or not b[2] or a[2] == b[2])
    return False


def sheet_index(sheet: list[dict]) -> list[tuple]:
    """(beach ids, local closing day, event type, event_id) of each sheet record placed on RIDOH's beach layer."""
    out = []
    for s in sheet or []:
        cj = (s.get("raw") or {}).get("coord_join") or {}
        ids = {str(m.get("beach_id")) for m in cj.get("matched") or [] if m.get("beach_id") is not None}
        if ids and s.get("started_at") and s.get("lat") is not None:
            out.append((ids, str(s["started_at"])[:10], s.get("event_type"), s["event_id"]))
    return out


def relink(r: dict, sheet_ix: list[tuple]) -> None:
    """duplicate_of for a record with no link yet: the one sheet record of the same RIDOH beach, type and local day."""
    raw = r.get("raw") or {}
    if r.get("duplicate_of") or not raw.get("coord_join"):
        return
    ids = {str(m.get("beach_id")) for m in raw["coord_join"].get("matched") or [] if m.get("beach_id") is not None}
    day = local_day(r["started_at"])
    same = [e for i, d, t, e in sheet_ix if i & ids and d == day and t == r.get("event_type")]
    if len(same) == 1:
        r["duplicate_of"] = same[0]
        raw["same_as_sheet"] = {"event_id": same[0], "basis": SAME_AS_SHEET}


def record_for(it: dict, b: dict, beaches: list[dict], fetched: str, sheet_ix: list[tuple]) -> dict:
    name, town = b["name"], b.get("town")
    cands, how = R.match_beach(name, town or "", beaches)
    lat, lon, spread, used = R.place(cands)
    hab = bool(R.HAB_RE.search(it.get("reason") or ""))
    et = "hab_advisory" if hab else "beach_closure"
    srid = f"{R.slugify(name)}:{R.slugify(town or 'na')}:node{it['node']}"
    raw = {"node": it["node"], "item_url": NODE_URL.format(it["node"]), "title": it["title"], "beach": name,
           "town": town, "reason": it.get("reason"), "start_basis": START_BASIS, "time_zone": "America/New_York",
           "_first_seen_at": fetched, "_last_seen_in_source": fetched, "page_url": URL, "state": "RI",
           "ident": list(ident(name, town, beaches))}
    if b.get("name_basis"):
        raw["name_basis"] = b["name_basis"]
    if lat is not None:
        raw["coord_join"] = {"layer": f"{R.BV}/0", "how": how,
                             "matched": [{"name": b2["name"], "beach_id": b2["beach_id"], "town": b2["town"]}
                                         for b2 in used]}
        slugs, wmatch, wdetail = R.waters_for(name, town or "", lat, lon)
        raw["water_placement"] = wdetail or None
        ids = {str(x["beach_id"]) for x in used}
        day = local_day(it["published_at"])
        same = [e for i, d, t, e in sheet_ix if i & ids and d == day and t == et]
    else:
        slugs, wmatch, same = [], "none", []
        raw.update(_placement="listed_only", placement_note=LISTED_ONLY_NOTE)
    dup = None
    if len(same) == 1:
        dup = same[0]
        raw["same_as_sheet"] = {"event_id": dup, "basis": SAME_AS_SHEET}
    reason = f" due to {it['reason']}" if it.get("reason") else ""
    where = f" in {town}" if town else ""
    return event(
        source_id=SOURCE_ID, source_record_id=srid, event_type=et, status="advisory_active",
        waterbody_text=f"{name} ({town})" if town else name, water_slugs=slugs, water_match=wmatch,
        lat=lat if lat is not None else None, lon=lon if lon is not None else None,
        coord_source="source" if lat is not None else None, coord_precision_m=spread,
        started_at=it["published_at"], published_at=it["published_at"], time_precision="minute",
        fetched_at=fetched, authority=AUTHORITY, source_url=NODE_URL.format(it["node"]), raw=raw, duplicate_of=dup,
        advice_text=f"RIDOH recommends closing the swimming area at {name}{where}{reason}.")


def build(page: str, fetched: str, previous: list[dict], sheet: list[dict] | None = None,
          beaches: list[dict] | None = None) -> tuple[list[dict], dict]:
    parsed = parse(page)
    beaches = beaches or []
    sheet_ix = sheet_index(sheet)
    records: dict[str, dict] = {}
    for p in previous:
        if isinstance(p, dict) and p.get("source_record_id"):
            records[p["source_record_id"]] = P.recleaned(p)
    opened = 0
    for it in sorted(parsed["items"], key=lambda x: (x["published_at"], x["node"])):
        if it["kind"] != "close":
            continue
        for b in it["beaches"]:
            rec = record_for(it, b, beaches, fetched, sheet_ix)
            old = records.get(rec["source_record_id"])
            if old:                     # read before: keep its first read, its end and the re-opening it was given
                oraw = old.get("raw") or {}
                rec["raw"]["_first_seen_at"] = oraw.get("_first_seen_at") or rec["raw"]["_first_seen_at"]
                for k in ("ended_at_precision", "end_basis", "reopened_by"):
                    if k in oraw:
                        rec["raw"][k] = oraw[k]
                if old.get("status") == "advisory_lifted":
                    rec.update(status="advisory_lifted", ended_at=old.get("ended_at"))
            else:
                opened += 1
            records[rec["source_record_id"]] = rec
    for r in records.values():          # a carried record gains its sheet link too (Astra P2-5)
        relink(r, sheet_ix)
    unmatched, ended = [], 0
    for it in sorted(parsed["items"], key=lambda x: (x["published_at"], x["node"])):
        if it["kind"] != "reopen" or parsed["unread"]:
            continue                    # a partial read ends nothing (Astra P1-2)
        for b in it["beaches"]:
            me = tuple(ident(b["name"], b.get("town"), beaches))
            hits = [r for r in records.values()
                    if r.get("status") == "advisory_active" and str(r.get("started_at") or "") < it["published_at"]
                    and r.get("event_type") == it.get("scope")
                    and same_beach(tuple((r.get("raw") or {}).get("ident") or ()), me)]
            done = [r for r in records.values() if ((r.get("raw") or {}).get("reopened_by") or {}).get("node")
                    == it["node"] and same_beach(tuple((r.get("raw") or {}).get("ident") or ()), me)]
            if not hits and not done:
                unmatched.append({"node": it["node"], "beach": b["name"], "town": b.get("town")})
            for r in hits:
                raw = dict(r.get("raw") or {})
                raw.update(ended_at_precision="minute", end_basis=END_BASIS,
                           reopened_by={"node": it["node"], "published_at": it["published_at"], "title": it["title"],
                                        "item_url": NODE_URL.format(it["node"])})
                r.update(status="advisory_lifted", ended_at=it["published_at"], raw=raw)
                ended += 1
    on_page = {i["node"] for i in parsed["items"]}
    for r in records.values():
        if (r.get("raw") or {}).get("node") in on_page:
            r["raw"]["_last_seen_in_source"] = fetched
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "on_page": parsed["on_page"], "items_read": len(parsed["items"]),
            "closing_items": sum(1 for i in parsed["items"] if i["kind"] == "close"),
            "reopening_items": sum(1 for i in parsed["items"] if i["kind"] == "reopen"),
            "notices": parsed["notices"], "unread": parsed["unread"], "opened": opened, "ended_this_read": ended,
            "unmatched_reopenings": unmatched,
            "same_as_sheet": sum(1 for r in out if r.get("duplicate_of")),
            "shown_on_their_own": sum(1 for r in out if not r.get("duplicate_of")),
            "listed_only": sorted({r["waterbody_text"] for r in out if (r.get("raw") or {}).get("_placement")
                                   == "listed_only"}),
            "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "cadence": "page read every run; RIDOH posts an item when it recommends closing or re-opening a beach, "
                       "Memorial Day to Labor Day",
            "coverage": "Rhode Island: the licensed beaches RIDOH posts recommendations for (no camps, no "
                        "cyanobacteria closures in 2026)"}
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
        parse(page)                                         # a bad page fails before anything else is read
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        sheet = (read_json(EVENTS_DIR / f"{SHEET_SOURCE}.json", {}) or {}).get("records", [])
        s = requests.Session()
        s.headers.update(HEADERS)
        recs, meta = build(page, fetched, prev, sheet, R.load_beaches(s))
        if "--file" not in argv:
            save_raw(SOURCE_ID, saved_form(parse(page)), "json")   # the parsed items only, never the page
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        P.write_refused(SOURCE_ID, P.safe_error(e), EVENTS_DIR)
        print(f"{SOURCE_ID}: FAILED {P.safe_error(e)}", file=sys.stderr)
        return 1
    if meta["unread"]:
        why = "; ".join(f"node {u.get('node', '?')}: {u['reason']}" for u in meta["unread"])
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error=f"unread items: {why}", meta=meta)
        print(f"{SOURCE_ID}: PARTIAL {len(meta['unread'])} item(s) unread -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['items_read']} items ({meta['closing_items']} closing, {meta['reopening_items']} "
          f"re-opening); {len(recs)} records, {meta['advisory_active']} active, {meta['same_as_sheet']} shown as the "
          f"sheet's -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
