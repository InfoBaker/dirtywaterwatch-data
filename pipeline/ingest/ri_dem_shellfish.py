"""Rhode Island DEM shellfish closures: the "Pollution-Related Conditional Area and Emergency Shellfish Closures" table.

Source
  https://dem.ri.gov/shellfish (registry: ri-ridem-shellfish-closure-page), which redirects to DEM's shellfish area
  monitoring page. The Office of Water Resources lists, under the heading above, an "Updated" date, the closure rain
  totals and a three-column table: Location, Status, Scheduled to Reopen ("Upper Bay Conditional Area (Area 1A)",
  "CLOSED", "Noon 11/14"; 2026-11-16: six areas CLOSED, table updated 11/7/2026). R.I. Gen. Laws § 20-8.1-3 makes
  the 24-hour shellfish hotline the primary notice of harvest restrictions; this table is DEM's published copy. In
  Rhode Island a shellfish closure after rain or a sewage release is the one legal public channel that reaches sewage
  releases into the bay. The page answers the pipeline's runner (runner probe 43877571236, 2026-11-16).

Record rules
  - One shellfish_closure record per row DEM lists CLOSED, DEM's own closure (status advisory_active, red: the
    authority's window, while DEM lists it). The area is named as DEM names it (the footnote asterisk dropped,
    raw.footnote_mark); the status word and the reopening text are DEM's (raw.status_text, raw.scheduled_reopen).
    A row DEM lists OPEN is no closure and makes no record.
  - Times: DEM's table gives no closure date. started_at is this site's first read that listed the closure
    (time_precision poll, raw.start_basis); the "Updated" date is DEM's publication of the table (published_at and
    source_updated_at, the day as given), never a start. "Scheduled to Reopen" is DEM's stated plan, kept as theirs
    (raw.scheduled_reopen: the text, and the time it names when it names one) and never an end: an area still listed
    CLOSED after its scheduled time stays red (raw.scheduled_reopen_passed says so). Rain totals are kept as DEM wrote
    them (raw.rain_totals_text). DEM gives no cause per area (raw.reason None, raw.reason_basis).
  - End: a closure that a complete healthy read no longer lists CLOSED (its row listed OPEN, or gone from a table
    DEM republished with a new Updated date; a row gone from a table with the same Updated date is an incomplete
    read, Astra review P1-1) ends at that read
    (advisory_lifted, raw.ended_at_precision poll, an upper bound; raw.end_seen_as). A closure listed again later is
    a new record (its key carries the first read's time, to the second). raw._last_seen_in_source is kept with
    raw._poll_confirmed (the status build's rule for a polled list): the colour runs to 14 days after the last read
    that listed the closure, so an end seen late never colours the unread time red, and a long unread gap is shown as
    unconfirmed (common.mark_unread_gaps).
  - Placement: a growing area is part of a water. DEM's area codes ("Area 1A", "Areas 8A, 8C") are joined by a
    reviewed table (AREAS) to DEM's own Conditional Closure polygons in the Shellfish Harvest Restrictions layer
    (June 2026; runner probe 43878309194): the marker is a point inside the area (the representative point of the
    polygon or of the union of its parts, 0.001 degree), placed on the water whose record holds the area, and never
    colours that whole water (raw._point_extent_only). A row whose codes are not in the table (an emergency closure
    elsewhere) is listed with DEM's words and placed on no water (raw._placement listed_only).
  - A bad read changes nothing: a failed request, a page without its closing tag, the heading, the "Updated" line or
    the table's three headings as expected, a table not read whole or with no row writes ok=False and keeps the
    earlier records. One row that cannot be read (an empty location, a status other than CLOSED or OPEN) is listed in
    meta.unread; the readable rows update, no earlier closure ends on that read (raw._held_unread), health stays false.
  - Privacy: only the heading, the Updated line, the rain totals line and the table are read (the contact paragraph
    below the table is not). Every field is cleaned before any save; the raw save is the parsed rows as JSON.

Run from pipeline/:  python -m ingest.ri_dem_shellfish [--file saved.html]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import nv_state_parks_hab as P

SOURCE_ID = "ri-ridem-shellfish-closure-page"
URL = "https://dem.ri.gov/shellfish"
AUTHORITY = "Rhode Island Department of Environmental Management (DEM), Office of Water Resources shellfish program"
ZONE = ZoneInfo("America/New_York")
LAYER = "https://risegis.ri.gov/hosting/rest/services/RIDEM/Shellfish_Harvest_Restrictions_FS/FeatureServer/0"

HEADING = re.compile(r"<h[1-6]\b[^>]*>\s*Pollution-Related\s+Conditional\s+Area\s+and\s+Emergency\s+Shellfish\s+"
                     r"Closures\s*</h[1-6]>", re.I)
UPDATED = re.compile(r"^\s*(?:<[^>]+>\s*)*<h[1-6]\b[^>]*>\s*Updated\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*</h[1-6]>", re.I)
RAIN = re.compile(r"<p\b[^>]*>\s*(?P<text>Closure\s+rain\s+totals:[^<]*)</p>", re.I)
TABLE = re.compile(r"<table\b[^>]*>(?P<body>.*?)</table>", re.S | re.I)
EXPECTED_HEAD = ["Location", "Status", "Scheduled to Reopen"]
CODES = re.compile(r"\(\s*Areas?\s+(?P<codes>[^)]+)\)", re.I)
CODE = re.compile(r"^\d{1,2}[A-Z]{0,2}(?:-[A-Z]{1,2})?$")
CLOSED = re.compile(r"^CLOSED(?:\s*[-:–(].*)?$", re.I)
OPEN = re.compile(r"^OPEN$", re.I)
REOPEN = re.compile(r"^(?:(?P<when>Noon)\s+)?(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?$", re.I)

# DEM's area codes -> DEM's own Conditional Closure polygons in the Shellfish Harvest Restrictions layer (June 2026
# edition, layer 0; read by the runner 2026-11-16, probe 43878309194), each the only Conditional Closure polygon(s) of
# that growing area. point: the representative point of the polygon (or of the union of its parts), 0.001 degree.
# water: the site's water record that holds the polygon (share of the polygon's area inside the record, checked
# 2026-11-16 against the water records): the water DEM names where the site has a record of it (Mount Hope Bay,
# Point Judith Pond, the Providence River, whose line runs 3.8 km through the area), else the record that holds it
# (Greenwich Bay and the Upper Bay lie in the Narragansett Bay record; the Kickemuit River has no record here and
# 98.6 percent of its area lies in the Mount Hope Bay record).
AREAS = {
    frozenset({"1A"}): {"objectids": [104], "sfcid": "GA1-1", "layer_name": 'Upper Narragansett Bay Area "A"',
                        "point": (41.7, -71.329), "water": "narragansett-bay-ri",
                        "water_basis": "98.6 percent of the area lies in the Narragansett Bay record"},
    frozenset({"16E"}): {"objectids": [113], "sfcid": "GA16-1", "layer_name": "Providence River",
                         "point": (41.731, -71.365), "water": "providence-river-ri",
                         "water_basis": "DEM names the Providence River; its record's line runs 3.8 km through the area"},
    frozenset({"8A", "8C"}): {"objectids": [94], "sfcid": "GA8-5", "layer_name": "Greenwich Bay",
                              "point": (41.676, -71.418), "water": "narragansett-bay-ri",
                              "water_basis": "Greenwich Bay has no record here; 99.4 percent of the area lies in the "
                                             "Narragansett Bay record"},
    frozenset({"17"}): {"objectids": [117], "sfcid": "GA17-1", "layer_name": "Mount Hope Bay",
                        "point": (41.678, -71.231), "water": "mount-hope-bay-ri",
                        "water_basis": "DEM names Mount Hope Bay; 99.6 percent of the area lies in its record"},
    frozenset({"5"}): {"objectids": [70], "sfcid": "GA5-4", "layer_name": "Mount Hope Bay; Kickemuit River and Vicinity",
                       "point": (41.708, -71.247), "water": "mount-hope-bay-ri",
                       "water_basis": "the Kickemuit River has no record here; 98.6 percent of the area lies in the "
                                      "Mount Hope Bay record"},
    frozenset({"10PJ-N", "10PJ-E"}): {"objectids": [110, 111], "sfcid": "GA10-8, GA10-9",
                                      "layer_name": "Point Judith Pond", "point": (41.412, -71.504),
                                      "water": "point-judith-pond-ri",
                                      "water_basis": "DEM names Point Judith Pond; 94 and 91 percent of its two parts "
                                                     "lie in its record"},
}
START_BASIS = ("this site's first read of DEM's table that listed the closure: DEM's table gives no closure date, and its "
               "'Updated' date is the table's publication, not the closure's start")
END_BASIS = ("the first complete read of DEM's table that no longer listed the area as closed, an upper bound: DEM's "
             "table gives no reopening time")
REOPEN_BASIS = "DEM's stated plan for reopening, as DEM wrote it: not a confirmed reopening, and never used as an end"
REASON_BASIS = ("DEM's table gives no cause per area; its heading lists conditional-area (rain) closures and emergency "
                "closures (harmful algal blooms, sewage releases) together")
POINT_BASIS = ("a point inside the area: the representative point of DEM's own polygon for it (Shellfish Harvest "
               "Restrictions layer, June 2026), 0.001 degree; the marker of a part of the water, which is never "
               "coloured whole")
LISTED_ONLY_NOTE = ("an area this site has no outline for: listed with DEM's words and placed on no water, so it "
                    "colours none")


def text_of(fragment: str) -> str:
    return P.text_of(fragment).replace(" ", " ").strip()


def area_codes(location: str) -> list[str]:
    """'Pt Judith Pond Conditional Areas (Areas 10PJ-N, 10PJ-E)' -> ['10PJ-N', '10PJ-E']."""
    m = CODES.search(location or "")
    if not m:
        return []
    return [c.strip().upper() for c in re.split(r"\s*,\s*|\s+and\s+|\s*&\s*", m.group("codes")) if c.strip()]


def us_date(s: str) -> date:
    m, d, y = (int(x) for x in s.split("/"))
    return date(y + 2000 if y < 100 else y, m, d)


def scheduled(text: str, updated: date) -> dict:
    """DEM's 'Scheduled to Reopen' text as theirs, with the time it names: 'Noon 11/14' -> 12:00 local on the 14th of
    November of the table's year (the next year when the month is well before the table's), precision hour; a date alone
    -> the day; anything else -> the text only."""
    out = {"text": text or None, "basis": REOPEN_BASIS}
    m = REOPEN.match(text or "")
    if not m:
        return out
    try:
        y = us_date(f"1/1/{m.group('y')}").year if m.group("y") else updated.year
        if not m.group("y") and int(m.group("m")) < updated.month - 6:
            y += 1
        day = date(y, int(m.group("m")), int(m.group("d")))
    except ValueError:
        return out
    if m.group("when"):
        out.update(at=datetime(day.year, day.month, day.day, 12, tzinfo=ZONE).isoformat(), precision="hour")
    else:
        out.update(at=day.isoformat(), precision="day")
    return out


def parse(page: str, fetched: str | None = None) -> dict:
    """{updated, rain_totals_text, rows, unread}; ValueError for a page that is not a complete reading."""
    if not re.search(r"</html\s*>", page or "", re.I):
        raise ValueError("the page is not complete (no closing html tag)")
    hs = list(HEADING.finditer(page))
    if len(hs) != 1:
        raise ValueError("the closures heading is not on the page once")
    after = page[hs[0].end():]
    up = UPDATED.match(after)
    if not up:
        raise ValueError("the 'Updated' line does not follow the closures heading")
    try:
        updated = us_date(up.group("date"))
    except ValueError:
        raise ValueError("the 'Updated' date cannot be read") from None
    fetched_day = (datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZONE).date()
                   if fetched else date.today())
    if updated > fetched_day + timedelta(days=1):
        raise ValueError("the 'Updated' date is after the read")
    t = TABLE.search(after)
    if not t:
        raise ValueError("the closures table is not complete")
    between = after[up.end(): t.start()]
    if re.search(r"<table\b|<h[1-6]\b", between, re.I):
        raise ValueError("another table or heading stands between the 'Updated' line and the closures table")
    rain = RAIN.search(between)
    body = t.group("body")
    if len(re.findall(r"<table\b", body, re.I)):
        raise ValueError("a table inside the closures table")
    head = [text_of(x) for x in re.findall(r"<th\b[^>]*>(.*?)</th>", body, re.S | re.I)]
    if head != EXPECTED_HEAD:
        raise ValueError("the closures table's headings are not Location, Status, Scheduled to Reopen")
    tb = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", body, re.S | re.I)
    if not tb:
        raise ValueError("the closures table has no body")
    trs = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tb.group(1), re.S | re.I)
    if len(re.findall(r"<tr\b", tb.group(1), re.I)) != len(trs) or not trs:
        raise ValueError("the closures table's rows are not completely readable")
    rows, unread = [], []
    for n, tr in enumerate(trs, start=1):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(cells) != 3 or len(re.findall(r"<td\b", tr, re.I)) != 3:
            raise ValueError("a row of the closures table does not have three cells")
        loc_raw, status, reopen = (text_of(c) for c in cells)
        mark = "*" in loc_raw
        loc = re.sub(r"\s*\*+\s*", " ", loc_raw).strip()
        loc = re.sub(r"\s+", " ", loc)
        if not loc:
            unread.append({"row": n, "reason": "a row with no location"})
            continue
        if CODES.search(loc) and not all(CODE.match(c) for c in area_codes(loc)):
            # only DEM's code form is read ("1A", "10PJ-N"): other text in the brackets is never kept (Astra P1-3)
            unread.append({"row": n, "location": P.clean_field(loc, "place"), "reason": "area codes the reader cannot take"})
            continue
        if CLOSED.match(status):
            kind = "closed"
        elif OPEN.match(status):
            kind = "open"
        else:
            unread.append({"row": n, "location": P.clean_field(loc, "place"), "area_key": key_of(
                {"codes": area_codes(loc), "location": P.clean_field(loc, "place")}),
                           "reason": "a status the reader does not take (not CLOSED or OPEN)"})
            continue
        rows.append({"row": n, "location": P.clean_field(loc, "place"), "footnote_mark": mark,
                     "codes": area_codes(loc), "status_text": P.clean_field(status, "place"), "kind": kind,
                     "scheduled_reopen": scheduled(P.clean_field(reopen, "place"), updated)})
    return {"updated": updated.isoformat(), "rain_totals_text": P.clean_text(text_of(rain.group("text")))[0]
            if rain else None, "rows": rows, "unread": unread}


def key_of(row: dict) -> str:
    return "areas-" + "-".join(P.slug(c) for c in sorted(row["codes"])) if row["codes"] else P.slug(row["location"])


def saved_form(parsed: dict) -> str:
    """What the raw save keeps: the parsed table as JSON; never the page's markup."""
    return json.dumps(P.deep_clean({"url": URL, **parsed}), ensure_ascii=False, indent=1)


def build(page: str, fetched: str, previous: list[dict]) -> tuple[list[dict], dict]:
    parsed = parse(page, fetched)
    unread = parsed["unread"]
    open_prev = {}
    for p in previous:
        raw = p.get("raw") or {}
        if p.get("status") == "advisory_active" and raw.get("area_key"):
            open_prev[raw["area_key"]] = p
    now = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    records: dict[str, dict] = {}
    opened = 0
    seen_keys = set()
    for row in parsed["rows"]:
        k = key_of(row)
        if row["kind"] != "closed":
            continue
        if k in seen_keys:
            unread.append({"row": row["row"], "location": row["location"], "reason": "an area listed twice"})
            continue
        seen_keys.add(k)
        prev = open_prev.get(k)
        praw = (prev or {}).get("raw") or {}
        srid = prev["source_record_id"] if prev else f"{k}:{P.episode_stamp(fetched)}"
        opened += prev is None
        sr = row["scheduled_reopen"]
        passed = None
        if sr.get("at"):
            at = datetime.fromisoformat(sr["at"]) if "T" in sr["at"] else \
                datetime.fromisoformat(sr["at"]).replace(tzinfo=ZONE) + timedelta(days=1)
            passed = at <= now
        updates = list(praw.get("table_updates") or [])
        if not updates or updates[-1].get("updated") != parsed["updated"] \
                or updates[-1].get("scheduled_reopen") != sr.get("text"):
            updates.append({"updated": parsed["updated"], "scheduled_reopen": sr.get("text"), "seen_at": fetched})
        area = AREAS.get(frozenset(row["codes"])) if row["codes"] else None
        raw = {"area_key": k, "location": row["location"], "area_codes": row["codes"],
               "footnote_mark": row["footnote_mark"], "status_text": row["status_text"],
               "scheduled_reopen": sr, "scheduled_reopen_passed": passed, "table_updated": parsed["updated"],
               "table_updates": P.deep_clean(updates), "rain_totals_text": parsed["rain_totals_text"],
               "reason": None, "reason_basis": REASON_BASIS, "start_basis": START_BASIS, "time_zone": "America/New_York",
               "_first_seen_at": praw.get("_first_seen_at") or fetched, "_last_seen_in_source": fetched,
               "_poll_confirmed": True, "page_url": URL, "state": "RI"}
        if passed:
            raw["scheduled_reopen_note"] = ("DEM's scheduled reopening has passed and DEM's table still lists the area "
                                            "CLOSED: shown as DEM lists it")
        if area:
            lat, lon = area["point"]
            raw.update(_point_extent_only=True, point_basis=POINT_BASIS,
                       area_polygon={"layer": LAYER, "objectids": area["objectids"], "sfcid": area["sfcid"],
                                     "layer_name": area["layer_name"], "edition": "June 2026"},
                       water_basis=area["water_basis"])
            slugs, match = [area["water"]], "geometry"
        else:
            lat = lon = None
            raw.update(_placement="listed_only", placement_note=LISTED_ONLY_NOTE)
            slugs, match = [], "none"
        reopen = (f" Scheduled to reopen: {sr['text']} (DEM's schedule, not a confirmed reopening)." if sr.get("text")
                  else "")
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="shellfish_closure", status="advisory_active",
            waterbody_text=row["location"], water_slugs=slugs, water_match=match,
            lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=None,
            started_at=prev["started_at"] if prev else fetched, time_precision="poll",
            published_at=parsed["updated"], source_updated_at=parsed["updated"], fetched_at=fetched,
            authority=AUTHORITY, source_url=URL, raw=raw,
            advice_text=(f"Shellfish harvest closure (Rhode Island DEM): {row['location']}, {row['status_text']}."
                         f"{reopen} DEM's table updated {parsed['updated']}."))
    listed_open = {key_of(r) for r in parsed["rows"] if r["kind"] == "open"}
    listed_closed = {key_of(r) for r in parsed["rows"] if r["kind"] == "closed"}
    for p in previous:
        raw = p.get("raw") or {}
        if p.get("status") == "advisory_active" and raw.get("area_key") not in listed_closed | listed_open \
                and raw.get("area_key") not in {u.get("area_key") for u in unread} \
                and raw.get("table_updated") == parsed["updated"]:
            # an area gone from a table DEM has not republished is not a reopening: the read is not complete (Astra
            # P1-1); a table with a new Updated date that no longer lists it, or a row listed OPEN, ends it
            unread.append({"row": None, "location": raw.get("location"),
                           "reason": "a closed area is missing from a table with the same Updated date"})
    lifted = held = kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in records:
            continue
        p = P.recleaned(p)
        raw = dict(p.get("raw") or {})
        if p.get("status") == "advisory_active":
            if unread:          # a partial read ends nothing: every earlier closure is held as it was
                raw["_held_unread"] = "the read was partial (" + str(len(unread)) + " row(s) unread): held as it was"
                held += 1
            else:
                p.update(status="advisory_lifted", ended_at=fetched)
                raw.update(ended_at_precision="poll", end_basis=END_BASIS, _unlisted_since=fetched,
                           end_seen_as="listed OPEN" if raw.get("area_key") in listed_open else "no longer listed")
                lifted += 1
        p["raw"] = raw
        records[sid] = p
        kept += 1
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "table_updated": parsed["updated"],
            "rain_totals_text": parsed["rain_totals_text"], "rows": len(parsed["rows"]) + len(parsed["unread"]),
            "closed": sum(1 for r in parsed["rows"] if r["kind"] == "closed"),
            "open": sum(1 for r in parsed["rows"] if r["kind"] == "open"), "unread": unread, "opened": opened,
            "lifted_this_read": lifted, "held_unread": held, "kept_from_previous": kept - lifted - held,
            "listed_only": sorted({r["raw"]["location"] for r in out if r["status"] == "advisory_active"
                                   and (r.get("raw") or {}).get("_placement") == "listed_only"}),
            "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "cadence": "page read every run; DEM updates the table after each closure and reopening",
            "coverage": "Rhode Island statewide: every conditional-area and emergency shellfish closure DEM's table "
                        "lists"}
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
            save_raw(SOURCE_ID, saved_form(parse(page, fetched)), "json")   # the parsed table only, never the page
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        P.write_refused(SOURCE_ID, P.safe_error(e), EVENTS_DIR)
        print(f"{SOURCE_ID}: FAILED {P.safe_error(e)}", file=sys.stderr)
        return 1
    if meta["unread"]:
        why = "; ".join(f"row {u['row']}: {u['reason']}" for u in meta["unread"])
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error=f"unread rows: {why}", meta=meta)
        print(f"{SOURCE_ID}: PARTIAL {len(meta['unread'])} row(s) unread -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: table updated {meta['table_updated']}, {meta['closed']} closed, {meta['open']} open; "
          f"{len(recs)} records, {meta['advisory_active']} active -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
