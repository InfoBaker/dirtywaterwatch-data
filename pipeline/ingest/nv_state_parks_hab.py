"""Nevada Division of State Parks harmful algal bloom advisories (the HAB Advisory page).

Source
  https://parks.nv.gov/about/hab-advisory (registry: nv-state-parks-hab), Nevada Division of State Parks. No key, no
  licence stated. The page holds three accordion sections, "HAB Watch Advisories", "HAB Warning Advisories" and
  "HAB Danger Advisories"; each lists the parks or lakes under that level, one bold heading per water with its update
  date ("Lahontan State Recreation Area (Updated May 11, 2026)") and a paragraph in the agency's words ("Lahontan
  Reservoir, located in Lahontan State Recreation Area, has been placed under a HAB Watch Advisory due to a possible
  Harmful Algae Bloom. Visual assessments have indicated a possible bloom."), or "None at this time." The page covers
  waters in state parks only ("For a full list of HAB sites in Nevada" it links the state's dashboard).

Record rules
  - One hab_advisory record per water while the page lists it, the authority's own advisory, quoted as theirs:
    status advisory_active, the level (Watch, Warning or Danger) in raw.level and the advice text, every level's
    sighting in raw.level_history (a downgrade or an upgrade changes the level of the same record, never a new one).
  - Times: the page gives an update date, not the date the advisory was issued, and no lift date. The update date is
    source_updated_at (day precision, Pacific time); started_at is the first read that listed the water
    (time_precision poll, raw.start_basis), never the update date; raw._last_seen_in_source is every read that lists
    it, so the status build ages an advisory out 14 days after the last read that showed it when the page stops being
    read. A water the page no longer lists, on a read that found all three sections, is advisory_lifted with ended_at
    that read (raw.ended_at_precision poll, raw._unlisted_since): the first read that saw it gone, an upper bound, not
    the agency's lift time. A water listed again later opens a new record (its key carries the first read's day).
  - A page on which any of the three sections cannot be found writes ok=False and the previous records stay: a
    template change or a failed request never lifts an advisory. A section reading "None at this time." lists no
    water at that level; it says nothing of waters outside the state parks.
  - Water: the paragraph's own words name it ("Lahontan Reservoir, located in ..."), else the heading. WATERS gives
    each known water its county (for the county-aware name placement and raw.placement_hint) and, where the U.S.
    Geological Survey's Geographic Names Information System holds the feature in that county, its point (coord_source
    "gnis", raw.point_basis and raw.point_url). A water not in WATERS keeps its name, placed by name only, with
    raw.placement_note saying so.
  - Clock: Nevada's (pipeline/zones.py nevada_zone, 49 CFR 71.9(b)): Pacific except West Wendover; raw.time_zone.
  - Privacy: only the headings and the advisory paragraphs are read; the page names no person. The raw save keeps the
    advisory sections only (the page's footer contact lines are not kept); strip_personal runs on raw.

Run from pipeline/:  python -m ingest.nv_state_parks_hab [--file saved.html]
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, write_events
from zones import nevada_zone

SOURCE_ID = "nv-state-parks-hab"
URL = "https://parks.nv.gov/about/hab-advisory"
AUTHORITY = "Nevada Division of State Parks (HAB advisories)"
LEVELS = ("Watch", "Warning", "Danger")
SECTION = re.compile(r'<label[^>]*>\s*HAB\s+(Watch|Warning|Danger)\s+Advisories\s*</label>(.*?)'
                     r'(?=<label[^>]*>\s*HAB\s+(?:Watch|Warning|Danger)\s+Advisories|</section>|<footer|$)', re.S | re.I)
HEADING = re.compile(r"<p>\s*<strong>\s*(?P<name>[^<(]+?)\s*\(\s*Updated:?\s*(?P<date>[A-Z][a-z]+\.?\s+\d{1,2},\s*\d{4})"
                     r"\s*\)\s*</strong>\s*</p>", re.I)
NONE = re.compile(r"None at this time", re.I)
GNIS = "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/{}"
# water as the parks' text names it -> (county, GNIS point or None). The points are features of the U.S. Geological
# Survey's Geographic Names Information System (The National Map's geonames service, layer Other Hydrographic Features,
# read 2026-11-14) in the county named; GNIS holds no Lahontan Reservoir or Washoe Lake, and its Rye Patch Reservoir is
# a different water in Lincoln County, so those three are placed by name and county only.
WATERS = {
    "Lahontan Reservoir": ("Churchill County", None),
    "Rye Patch Reservoir": ("Pershing County", None),
    "Washoe Lake": ("Washoe County", None),
    "Marlette Lake": ("Carson City", ("Marlette Lake", 39.174, -119.902, 860477)),
    "Wild Horse Reservoir": ("Elko County", ("Wild Horse Reservoir", 41.671, -115.809, 862000)),
}
START_BASIS = ("the first read of the parks' page that listed this water: the page gives the date of its last update, "
               "not the date the advisory was issued")
END_BASIS = ("the first read of the parks' page that no longer listed this water, an upper bound: the page gives no "
             "lift date")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def text_of(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t).replace("\xa0", " ")).strip()


def parse_date(s: str) -> str:
    s = re.sub(r"\s+", " ", s.replace(".", "")).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d,%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"unreadable update date {s!r}")


def water_of(heading: str, text: str) -> str:
    """The water the paragraph names ("Lahontan Reservoir, located in ..."), else the heading."""
    m = re.match(r"\s*([A-Z][A-Za-z' .&-]+?),\s+located in\b", text)
    name = (m.group(1) if m else heading).strip()
    return re.sub(r"\s+", " ", name)


def parse(page: str) -> tuple[list[dict], str]:
    """([{level, heading, water, updated, text}], the advisory sections' html); ValueError when a section is missing."""
    found: dict[str, str] = {}
    for m in SECTION.finditer(page):
        found.setdefault(m.group(1).title(), m.group(2))
    missing = [lv for lv in LEVELS if lv not in found]
    if missing:
        raise ValueError(f"advisory sections not found on the page: {', '.join(missing)}")
    out = []
    for lv in LEVELS:
        body = found[lv]
        heads = list(HEADING.finditer(body))
        if not heads and not NONE.search(text_of(body)):
            raise ValueError(f"the {lv} section lists no water and does not say 'None at this time'")
        for i, h in enumerate(heads):
            seg = body[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
            seg = re.split(r"</div>", seg)[0]
            text = text_of(seg)
            heading = text_of(h.group("name"))
            out.append({"level": lv, "heading": heading, "water": water_of(heading, text),
                        "updated": parse_date(h.group("date")), "text": scrub_text(text)})
    sections = "\n".join(f"<section data-level=\"{lv}\">{found[lv]}</section>" for lv in LEVELS)
    return out, sections


def local_day(fetched: str, tz: str) -> str:
    return datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date().isoformat()


def build(page: str, fetched: str, previous: list[dict]) -> tuple[list[dict], dict]:
    items, _ = parse(page)
    # one entry per water: a water listed twice (two levels at once) keeps the higher level, the other in raw
    by_water: dict[str, dict] = {}
    for it in items:
        k = slug(it["water"])
        if k in by_water:
            keep, other = sorted([by_water[k], it], key=lambda x: LEVELS.index(x["level"]), reverse=True)
            keep.setdefault("also_listed", []).append({"level": other["level"], "updated": other["updated"],
                                                       "heading": other["heading"]})
            by_water[k] = keep
        else:
            by_water[k] = it
    open_prev = {}
    for p in previous:
        raw = p.get("raw") or {}
        if p.get("status") == "advisory_active" and raw.get("water_key"):
            open_prev[raw["water_key"]] = p
    records: dict[str, dict] = {}
    opened = 0
    for k, it in by_water.items():
        county, gnis = WATERS.get(it["water"], (None, None))
        tz = nevada_zone(*(gnis[1:3] if gnis else (None, None)))
        prev = open_prev.get(k)
        praw = (prev or {}).get("raw") or {}
        srid = prev["source_record_id"] if prev else f"{k}:{local_day(fetched, tz)}"
        opened += prev is None
        started = prev["started_at"] if prev else fetched
        history = list(praw.get("level_history") or [])
        if not history or history[-1].get("level") != it["level"] or history[-1].get("updated") != it["updated"]:
            history.append({"level": it["level"], "updated": it["updated"], "seen_at": fetched})
        raw = {"water_key": k, "heading": it["heading"], "level": it["level"], "level_history": history,
               "updated_date": it["updated"], "time_zone": tz,
               "time_zone_basis": "Nevada: Pacific time except West Wendover (49 CFR 71.9(b))",
               "start_basis": START_BASIS, "_first_seen_at": praw.get("_first_seen_at") or fetched,
               "_last_seen_in_source": fetched, "page_url": URL,
               "updated_note": "the parks' update date beside the water's name, Pacific time; not an issue date",
               "placement_hint": {"name": it["water"], "county": county, "state": "NV",
                                  "basis": "the water the parks' advisory names, in the county that holds it"}}
        if it.get("also_listed"):
            raw["also_listed"] = it["also_listed"]
        lat = lon = None
        if gnis:
            lat, lon = gnis[1], gnis[2]
            raw["point_basis"] = f"{gnis[0]}: USGS GNIS feature {gnis[3]} (Other Hydrographic Features), {county}"
            raw["point_url"] = GNIS.format(gnis[3])
        elif it["water"] not in WATERS:
            raw["placement_note"] = "a water the crosswalk does not know: placed by its name only"
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory", status="advisory_active",
            waterbody_text=it["water"], lat=lat, lon=lon, coord_source="gnis" if gnis else None,
            coord_precision_m=500 if gnis else None, started_at=started, time_precision="poll",
            source_updated_at=it["updated"], fetched_at=fetched, authority=AUTHORITY,
            advice_text=f"HAB {it['level']} Advisory (Nevada State Parks): {it['text']}", source_url=URL, raw=raw)
    lifted = kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in records:
            continue
        p = dict(p)
        raw = dict(p.get("raw") or {})
        if p.get("status") == "advisory_active":
            p.update(status="advisory_lifted", ended_at=fetched)
            raw.update(ended_at_precision="poll", end_basis=END_BASIS, _unlisted_since=fetched)
            lifted += 1
        p["raw"] = raw
        records[sid] = p
        kept += 1
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "on_page": len(items),
            "by_level": {lv: sum(1 for it in items if it["level"] == lv) for lv in LEVELS},
            "opened": opened, "lifted_this_read": lifted, "kept_from_previous": kept - lifted,
            "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "cadence": "page read every run; the parks update it when a level changes, with no fixed schedule",
            "coverage": "waters in Nevada state parks only"}
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
        recs, meta = build(page, fetched, prev)
        if "--file" not in argv:
            save_raw(SOURCE_ID, parse(page)[1], "html")      # the advisory sections only
            if r.headers.get("Last-Modified"):
                meta["page_last_modified"] = parsedate_to_datetime(r.headers["Last-Modified"]).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['on_page']} on the page {meta['by_level']}, {len(recs)} records, "
          f"{meta['advisory_active']} active -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
