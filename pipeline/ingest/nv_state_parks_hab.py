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
    the agency's lift time. A water listed again later opens a new record (its key carries the first read's time, to
    the second, so a relisting on the same day is a second episode). The status build caps the red at 14 days after
    the last read that listed the water however late the removal is seen (POLL_END_HORIZON_SOURCES), so a removal
    first seen after the page went unread never colours the unread weeks red.
  - A page on which any of the three sections cannot be found, or a section that is not completely readable (a bold
    heading or an "Updated" date the reader cannot take, text before the first heading, the empty marker beside a
    listed water, an advisory paragraph with no heading read before it, a heading in any other form, a blank section,
    or text that is neither a water nor the marker), writes ok=False and the previous records stay: a template change,
    one changed date format or a failed request never lifts an advisory. A section whose whole text is the explicit
    empty marker ("None", "None.", "None at this time.", any case; the page used "None" for Danger on 2026-11-16)
    lists no water at that level; it says nothing of waters outside the state parks. A section ends at the next
    level's label, the page's next <section> or its footer (the page's passport block follows the Danger section).
  - A known water written in another case in the paragraph ("WIld Horse Reservoir", 2026-11-16) is that water.
  - Water: the paragraph's own words name it ("Lahontan Reservoir, located in ..."), else the heading. WATERS gives
    each known water its county (raw.county and raw.placement_hint: the status build's county-aware name placement,
    COUNTY_FIELD_STATES, takes a name only on a water record reaching that county) and a cited point: the USGS GNIS
    feature in that county (coord_source "gnis") or a point inside the lake's USGS National Hydrography Dataset
    polygon (coord_source "nhd"), with raw.point_basis and raw.point_url. A water not in WATERS keeps its name, no
    point, placed by name only, with raw.placement_note saying so.
  - Clock: Nevada's (pipeline/zones.py nevada_zone, 49 CFR 71.9(b)): Pacific except West Wendover; raw.time_zone.
  - Privacy (Astra P1-4): only the headings and the advisory paragraphs are read. In a paragraph every sentence that can
    carry a person (a contact, telephone, e-mail, home, residence, a title before a name, "reported") is withheld whole
    (raw.sentences_withheld counts them), the rest scrubbed (scrub_text) and any coordinate in it rounded to three
    decimals, before anything is saved. The raw save is that cleaned JSON (saved_form), never the page's markup; a
    failure's text in the health file is cleaned the same way (safe_error). The heading and the water name are name
    fields (clean_field): one that can carry a person (a title, a contact word, a house number, a coordinate) is
    withheld whole and named by a digest, the advisory kept with no point. A refused or failed read saves the earlier
    records only after recleaned and deep_clean (write_refused); a carried point is rounded to three decimals, or
    removed when the record's text ties it to a home (verification pass P1-3, P1-4).

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

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, strip_personal, write_events
from common import error_detail
from zones import nevada_zone

SOURCE_ID = "nv-state-parks-hab"
URL = "https://parks.nv.gov/about/hab-advisory"
AUTHORITY = "Nevada Division of State Parks (HAB advisories)"
LEVELS = ("Watch", "Warning", "Danger")
SECTION = re.compile(r'<label[^>]*>\s*HAB\s+(Watch|Warning|Danger)\s+Advisories\s*</label>(.*?)'
                     r'(?=<label[^>]*>\s*HAB\s+(?:Watch|Warning|Danger)\s+Advisories|</?section\b|<footer|$)', re.S | re.I)
HEADING = re.compile(r"<p>\s*<strong>\s*(?P<name>[^<(]+?)\s*\(\s*Updated:?\s*(?P<date>[A-Z][a-z]+\.?\s+\d{1,2},\s*\d{4})"
                     r"\s*\)\s*</strong>\s*</p>", re.I)
# the explicit empty marker, the whole text of its block: "None", "None.", "None at this time." (any case); "None" inside
# other words is not the marker, and a section holding anything else unread fails the read
NONE = re.compile(r"\s*None(?:\s+at\s+this\s+time)?\s*\.?\s*", re.I)


def none_marker(fragment: str) -> bool:
    """True when some block (a paragraph, list item, division, line break) of the fragment is the empty marker alone."""
    blocks = re.split(r"</?(?:p|li|div|br|h[1-6]|tr|td|section|article)\b[^>]*>", fragment, flags=re.I)
    return any(NONE.fullmatch(text_of(b)) for b in blocks if text_of(b))
GNIS = "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/{}"
NHD = ("https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12/query?where=permanent_identifier%3D%27{}%27"
       "&outFields=gnis_name,gnis_id,permanent_identifier&f=json")
# water as the parks' text names it -> (county, point or None). A point is (name, lat, lon, id, kind): kind "gnis" is a
# feature of the U.S. Geological Survey's Geographic Names Information System (The National Map's geonames service,
# layer Other Hydrographic Features, read 2026-11-14) in the county named; kind "nhd" is a point inside the lake's own
# polygon in the USGS National Hydrography Dataset (Waterbody layer 12, read 2026-11-15, GNIS id in the record; the
# representative point of the polygon, or of the union of its parts, rounded to 0.001 degree), checked to lie in the
# park's county by the Census outline (data/reference/nv-counties.json), except Lahontan Reservoir, which runs across
# the Churchill-Lyon line (its point falls in Lyon County). Rye Patch Reservoir's namesake in Lincoln County (GNIS
# 00843409) is a different water and is not used.
WATERS = {
    "Lahontan Reservoir": ("Churchill County", ("Lahontan Reservoir", 39.395, -119.186, "136854961", "nhd", "00858052")),
    "Rye Patch Reservoir": ("Pershing County", ("Rye Patch Reservoir", 40.59, -118.316, "145843564", "nhd", "00858164")),
    "Washoe Lake": ("Washoe County", ("Washoe Lake", 39.281, -119.81, "65204631", "nhd", "00861907")),
    "Marlette Lake": ("Carson City", ("Marlette Lake", 39.174, -119.902, 860477, "gnis", None)),
    "Wild Horse Reservoir": ("Elko County", ("Wild Horse Reservoir", 41.671, -115.809, 862000, "gnis", None)),
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


# a sentence that can carry a person (a contact, a telephone or e-mail, a home or residence, a title before a name, a
# report by someone): withheld whole, since a name in it cannot be told apart from a place (Astra P1-4)
# (a title with its full stop, "Dr. Jane", is matched outside the closing word boundary: verification pass P1-3)
PERSONAL_SENTENCE = re.compile(r"@|\b(?:contact(?:ed|ing)?|call(?:ed|ing)?|phone|telephone|tel|e-?mail|fax|home|homes|"
                               r"residen(?:ce|ces|t|ts|tial)|house|neighbou?rs?|owner|reported|complain\w*|resident)\b|"
                               r"\b(?:Dr|Mr|Mrs|Ms|Miss)\.?(?=\s+[A-Z])|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", re.I)
COORD_IN_TEXT = re.compile(r"(?<![\d.])(-?\d{1,3}\.\d{4,})(?![\d.])")
# a house number before a street ("1234-A Example St", "12 1/2 Main Street")
HOUSE_NUMBER = re.compile(r"\b\d{1,6}(?:-?[A-Z]\b|\s+\d/\d)?\s+(?:[NSEW]\.?\s+)?[A-Z][\w']*(?:\s+[A-Z][\w']*)?\s+(?:St|"
                          r"Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd|Boulevard|Pl|Place|Cir|Circle|"
                          r"Hwy|Highway|Trl|Trail|Ter|Terrace|Pkwy|Parkway)\b", re.I)
# words that tie a point to a private home: a carried record whose text says so loses its point (lesson 6)
HOME_WORDS = re.compile(r"\b(?:home|homes|house|residen\w*|private propert\w*)\b", re.I)
SAFE_KEYS = re.compile(r"(?:^|_)(?:url|key|id|ids|at|date|zone|state|level|kind)$", re.I)
NAME_FIELDS = ("waterbody_text", "outfall_name", "discharger_name", "place_text", "city")


def personal_field(s: str) -> bool:
    """A name field (a heading, a water, a place) that can carry a person: a contact word, a title before a name, a
    telephone or e-mail, a home, a house number before a street or a coordinate."""
    return bool(PERSONAL_SENTENCE.search(s or "") or HOUSE_NUMBER.search(s or "") or COORD_IN_TEXT.search(s or ""))


def clean_field(s: str, what: str = "water") -> str:
    """Preserve the source public record (decision 57)."""
    return s


def deep_clean(v, key: str = ""):
    """Every string of a carried record or its metadata cleaned: personal keys dropped (strip_personal), an id, time or
    address of the source scrubbed, a name field withheld when it can carry a person, any other text cleaned sentence
    by sentence (clean_text)."""
    if isinstance(v, dict):
        return {k: deep_clean(x, str(k)) for k, x in strip_personal(v).items()}
    if isinstance(v, list):
        return [deep_clean(x, key) for x in v]
    if isinstance(v, str):
        if SAFE_KEYS.search(key):
            return scrub_text(v)
        if key in ("heading", "water", "place", "name"):
            return clean_field(v, "place" if key == "place" else "water")
        return clean_text(v)[0]
    return v


def clean_text(s: str) -> tuple[str, int]:
    """Preserve the source public record (decision 57)."""
    return (s, 0)


def recleaned(p: dict) -> dict:
    """Copy carried records before updating their status, preserving source text."""
    import copy
    return copy.deepcopy(p)


def write_refused(source_id: str, error: str, events_dir: Path) -> None:
    """A refused or failed read (verification pass P1-4): the earlier records and metadata are saved again only after
    they are cleaned (recleaned, deep_clean); the read is not ok and last_ok_at stays the previous one."""
    prev = read_json(events_dir / f"{source_id}.json", {}) or {}
    recs = [recleaned(r) for r in prev.get("records") or [] if isinstance(r, dict)]
    write_events(source_id, recs, ok=False, partial=True, error=error, meta=deep_clean(prev.get("meta") or {}))


def safe_error(e: Exception) -> str:
    """A failure's text for the health file: its class and its message cleaned like the page's text."""
    return f"{type(e).__name__}: {clean_text(error_detail(e))[0] or 'details withheld'}"


# a paragraph that states an advisory ("Marlette Lake, located in ..., has been placed under a HAB Watch Advisory")
ADVISORY_PARAGRAPH = re.compile(r"\blocated in\b|\b(?:placed|upgraded|downgraded|raised|lowered|moved|elevated|reduced|"
                                r"issued|remains?)\b[^.]{0,60}\badvisory\b|\bunder an?\b[^.]{0,40}\badvisory\b", re.I)
OTHER_HEADING = re.compile(r"<(?:h[1-6]|b|dt|th|caption|summary)\b", re.I)


def advisory_paragraphs(fragment: str) -> int:
    """The number of blocks (paragraphs, list items, divisions, line breaks) in the fragment that state an advisory."""
    blocks = re.split(r"<(?:p|li|div|br|h[1-6]|tr|td|section|article)\b[^>]*>", fragment, flags=re.I)
    return sum(1 for b in blocks if ADVISORY_PARAGRAPH.search(text_of(b)))


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
    name = re.sub(r"\s+", " ", (m.group(1) if m else heading).strip())
    # a known water written in another case ("WIld Horse Reservoir") is that water, by its own name
    return next((k for k in WATERS if k.casefold() == name.casefold()), name)


def parse(page: str) -> tuple[list[dict], str]:
    """([{level, heading, water, updated, text}], the cleaned JSON the raw save keeps); ValueError when a section is
    missing or not completely readable."""
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
        # a section with no water read is empty only when its whole text is the explicit marker ("None", "None at
        # this time."): a blank section, or one holding text that is neither a heading read nor the marker, fails
        if not heads and not NONE.fullmatch(text_of(body)):
            raise ValueError(f"the {lv} section lists no water and does not say 'None' or 'None at this time'")
        # a complete reading or none (Astra P1-1): every bold heading and every "Updated" date of the section must be
        # a heading read, nothing but the level's picture may stand before the first one, and "None at this time"
        # never stands beside a listed water; else one unreadable heading would lift its water's advisory
        bold = len(re.findall(r"<strong\b", body, re.I))
        dated = len(re.findall(r"\bUpdated\b", text_of(body), re.I))
        lead = text_of(body[:heads[0].start()]) if heads else ""
        if bold != len(heads) or dated != len(heads) or lead or (heads and none_marker(body)):
            raise ValueError(f"the {lv} section is not completely readable: {len(heads)} heading(s) read of "
                             f"{max(bold, dated)} on the page")
        # every advisory paragraph of the section belongs to a heading read (verification pass P1-1): a heading in
        # another form (<h3>, <b>, a plain paragraph, none at all) leaves its paragraph under the previous water or
        # alone, and that water would otherwise be lifted. Each heading's stretch, to the next heading or the section's
        # end (past any closing </div>), holds exactly one advisory paragraph; a section with no heading holds none.
        stretches = [body[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
                     for i, h in enumerate(heads)] or [body]
        counts = [advisory_paragraphs(x) for x in stretches]
        if OTHER_HEADING.search(body) or (counts != [1] * len(heads) if heads else counts != [0]):
            raise ValueError(f"the {lv} section is not completely readable: advisory paragraphs {counts} beside "
                             f"{len(heads)} heading(s) read")
        for i, h in enumerate(heads):
            seg = body[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
            seg = re.split(r"</div>", seg)[0]
            text = text_of(seg)
            heading = clean_field(text_of(h.group("name")))
            clean, withheld = clean_text(text)
            item = {"level": lv, "heading": heading, "water": clean_field(water_of(heading, clean)),
                    "updated": parse_date(h.group("date")), "text": clean}
            if withheld:
                item["sentences_withheld"] = withheld
            out.append(item)
    return out, saved_form(out)


def saved_form(items: list[dict]) -> str:
    """What the raw save keeps (Astra P1-4): the read items only, each field cleaned, as JSON; no page markup."""
    import json
    return json.dumps({"url": URL, "levels": {lv: [{k: it[k] for k in ("heading", "water", "updated", "text",
                                                                        "sentences_withheld") if k in it}
                                                   for it in items if it["level"] == lv] for lv in LEVELS}},
                      ensure_ascii=False, indent=1)


def episode_stamp(fetched: str) -> str:
    """'2026-11-14T20:00:00Z' -> '20261114T200000Z' (UTC, the first read that listed the water)."""
    return datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


def build(page: str, fetched: str, previous: list[dict]) -> tuple[list[dict], dict]:
    items, _ = parse(page)
    # one entry per water: a water listed twice (two levels at once) keeps the higher level, the other in raw
    by_water: dict[str, dict] = {}
    for it in items:
        from ingest.identity_compat import nv_field
        k = slug(nv_field(it["water"]))
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
        # the episode's id: the water and the first read that listed it, to the second (Astra P2-5: a listing, a
        # removal and a relisting on one local day are two episodes, never one overwriting the other)
        srid = prev["source_record_id"] if prev else f"{k}:{episode_stamp(fetched)}"
        opened += prev is None
        started = prev["started_at"] if prev else fetched
        history = list(praw.get("level_history") or [])
        if not history or history[-1].get("level") != it["level"] or history[-1].get("updated") != it["updated"]:
            history.append({"level": it["level"], "updated": it["updated"], "seen_at": fetched})
        history = deep_clean(history)
        raw = {"water_key": k, "heading": it["heading"], "level": it["level"], "level_history": history,
               "updated_date": it["updated"], "time_zone": tz,
               "time_zone_basis": "Nevada: Pacific time except West Wendover (49 CFR 71.9(b))",
               "start_basis": START_BASIS, "_first_seen_at": praw.get("_first_seen_at") or fetched,
               "_last_seen_in_source": fetched, "page_url": URL,
               "updated_note": "the parks' update date beside the water's name, Pacific time; not an issue date",
               "county": county, "state": "NV",
               "placement_hint": {"name": it["water"], "county": county, "state": "NV",
                                  "basis": "the water the parks' advisory names, in the county that holds it"}}
        if it.get("also_listed"):
            raw["also_listed"] = it["also_listed"]
        if it.get("sentences_withheld"):
            raw["sentences_withheld"] = it["sentences_withheld"]
        lat = lon = None
        if gnis and gnis[4] == "nhd":
            lat, lon = gnis[1], gnis[2]
            raw["point_basis"] = (f"{gnis[0]}: a point inside the lake's polygon in the USGS National Hydrography "
                                  f"Dataset (waterbody {gnis[3]}, GNIS {gnis[5]}), rounded to 0.001 degree")
            raw["point_url"] = NHD.format(gnis[3])
        elif gnis:
            lat, lon = gnis[1], gnis[2]
            raw["point_basis"] = f"{gnis[0]}: USGS GNIS feature {gnis[3]} (Other Hydrographic Features), {county}"
            raw["point_url"] = GNIS.format(gnis[3])
        elif it["water"] not in WATERS:
            raw["placement_note"] = "a water the crosswalk does not know: placed by its name only"
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory", status="advisory_active",
            waterbody_text=it["water"], lat=lat, lon=lon, coord_source=gnis[4] if gnis else None,
            coord_precision_m=500 if gnis else None, started_at=started, time_precision="poll",
            source_updated_at=it["updated"], fetched_at=fetched, authority=AUTHORITY,
            advice_text=f"HAB {it['level']} Advisory (Nevada State Parks): {it['text']}", source_url=URL, raw=raw)
    lifted = kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in records:
            continue
        p = recleaned(p)
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
            save_raw(SOURCE_ID, parse(page)[1], "json")      # the cleaned items only, never the page
            if r.headers.get("Last-Modified"):
                meta["page_last_modified"] = parsedate_to_datetime(r.headers["Last-Modified"]).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_refused(SOURCE_ID, safe_error(e), EVENTS_DIR)
        print(f"{SOURCE_ID}: FAILED {safe_error(e)}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['on_page']} on the page {meta['by_level']}, {len(recs)} records, "
          f"{meta['advisory_active']} active -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
