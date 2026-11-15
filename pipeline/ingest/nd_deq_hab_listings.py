"""North Dakota Department of Environmental Quality: harmful algal bloom advisories and warnings (the listing PDF)
-> data/build/events/nd-deq-hab-listings.json

Source
  https://www.deq.nd.gov/publications/WQ/3_WM/HABs/HABsListings.pdf (registry: nd-deq-hab-listings), linked from DEQ's
  harmful algal bloom page (https://deq.nd.gov/WQ/3_Watershed_Mgmt/8_HABS/Habs.aspx). One page, two tables: "Advisories"
  and "Warning", each row a lake, its county (two joined by "/" for a lake on a county line: "Ramsey/Benson") and a
  "Date Posted". No key, no terms stated; one request a run. DEQ's notices say the web listing is updated from 1 May to
  31 December and that routine monitoring of the 2026 season ended on 30 September. On 2026-11-14 (file last modified
  2026-10-08 19:44 UTC): 14 advisories (posted 2026-07-16 to 2026-10-05) and 6 warnings (2026-06-29 to 2026-10-08).
  DEQ's categories (its HAB program page): an advisory means a bloom is present; a warning means the bloom covers a
  significant part of the water and toxins are above the recreational threshold. Blooms, never sewage.

Reading the PDF
  The page's text is split over eight content streams (its /Contents array), and some table cells are cut where one
  stream ends and the next begins ("Bowman - Haley Dam", the county of "Lake Darling"): the streams are joined in the
  page's order before the text is read (ingest.nh_pdftext's operators), then rows are rebuilt by their y position and
  the columns by x (the lake left of 300 pt, the county to 450 pt, the date beyond). Letters drawn apart ("N" + "orth
  Lake Washington") are joined. A file in which either table heading is missing, or any row cannot be read whole as a
  lake, county and date, writes ok=False and the previous records stay, so nothing is lifted by a bad read (review
  2026-11-14 P1-5). Re-review P1-4: a row's county must be a North Dakota county (data/reference/nd-counties.json),
  so a lost county cell fails the read instead of changing the record's key; a file of more than one page, or one
  whose content stream is missing or cannot be decoded, fails; a table with no rows counts as empty only where it
  says so ("None", "No current advisories"), else the read fails and nothing is lifted.

Record rules
  - One hab_advisory record per observed period of a posting: source_record_id <lake>:<counties in alphabetical
    order>:<level>:<Date Posted> (DEQ gives no row id). raw.level "advisory" or "warning" (the table the row is in). A
    lake moved to the other table or reposted with a new date is a new posting and a new record; the earlier one ends
    at the read that no longer lists it (review P2-1). The same posting listed again after it left the listing is a
    new period, <key>~2, ~3 ..., started at the read that shows it again (time_precision poll, raw.returned_after the
    earlier period's end): the earlier period keeps its end, so the gap is never coloured (re-review P2-1).
  - started_at: the Date Posted, precision day, DEQ's own posting of the advisory or warning (raw.date_note); bloom
    onset and sampling are not given. published_at the same day. source_updated_at the file's Last-Modified time.
  - Status: advisory_active while the row is listed (raw._last_seen_in_source each read: DEQ's own window, red); the
    first read without the row ends it: advisory_lifted, ended_at that read's time, raw.ended_at_precision "poll"
    (DEQ gives no lifting date; the read bounds it) and raw._unlisted_since. A row that comes back reopens the record.
    A file that cannot be read never ends anything.
  - Clock: raw.time_zone from the county (pipeline/zones.py north_dakota_zone, 49 CFR 71.7(a)): Mountain for the
    southwestern counties (Lake Tschida in Grant County, Bowman-Haley Dam in Bowman County, Patterson Lake in Stark
    County, Lake Ilo in Dunn County), Central elsewhere; a county set read in Mountain time if any county is.
  - Marker: the listing gives no coordinates; the cited point of the one GNIS lake of its name in a county DEQ lists
    (data/reference/nd-hab-lake-points.json, scripts/nd_hab_lake_points.py: inside its NHD outline, coord_source
    nhd_waterbody, else the GNIS gazetteer point, coord_source gnis_point; 15 of the 20 lakes of 2026-11-14) is the
    record's lat/lon (raw.marker_point with the GNIS id), so the advisory draws its marker on a large lake too (review
    P1-1). A lake with no identified water gets none; it stays in the records, filed under ND, and the state text
    names it.
    raw.advisory_extent "named_water": DEQ lists the lake, so a listed advisory placed on a lake colours that lake
    whatever its size and keeps its marker where it has a point (re-review 2026-11-14 P1-1).
  - Place: placed by the lake's name, county-aware: raw.county the first county DEQ gives (the status
    build's COUNTY_FIELD_STATES), raw.counties all of them, raw.placement_hint {name, counties, state}. A lake with no
    water record is listed in research/nd/receiving-waters-missing.json with its counties.
  - Privacy: lake, county and date only; the listing names no person.

Run from pipeline/:  python -m ingest.nd_deq_hab_listings [--file saved.pdf]
"""
from __future__ import annotations

import json
import re
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import zones
from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import nh_pdftext as P

SOURCE_ID = "nd-deq-hab-listings"
URL = "https://www.deq.nd.gov/publications/WQ/3_WM/HABs/HABsListings.pdf"
PAGE_URL = "https://deq.nd.gov/WQ/3_Watershed_Mgmt/8_HABS/Habs.aspx"
AUTHORITY = "North Dakota Department of Environmental Quality (harmful algal bloom advisories and warnings)"
LEVEL_MEANING = {"advisory": "DEQ's advisory: a harmful algal bloom is present",
                 "warning": ("DEQ's warning: the bloom covers a significant part of the water and toxins are above the "
                             "recreational threshold")}
DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
# a table's own statement that it is empty ("None", "No current advisories"): the only evidence of an empty table
NONE_SAID = re.compile(r"^(?:none|no(?:current)?(?:advisories|advisory|warnings?)(?:atthistime)?)\.?$")


def _nd_counties() -> set[str]:
    doc = json.loads((Path(__file__).resolve().parents[2] / "data" / "reference" / "nd-counties.json").read_text())
    return {c["county"].removesuffix(" County") for c in doc["counties"]}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


PAGE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")


def page_items(pdf: bytes) -> list[dict]:
    """Positioned text of the listing's one page, its content streams joined in the page's /Contents order (a cell cut
    between two streams is read whole). ValueError when the file has more or fewer than one page (a listing that runs
    onto a second page is not read in part) or a content stream the page names is missing or cannot be decoded
    (re-review 2026-11-14 P1-4)."""
    objs = P._streams(pdf)
    pages = [head for head, _ in objs.values() if PAGE.search(head)]
    if len(pages) != 1:
        raise ValueError(f"the listing has {len(pages)} pages; only a one-page listing is read whole")
    m = re.search(rb"/Contents\s*\[([^\]]*)\]", pages[0]) or re.search(rb"/Contents\s+(\d+\s+\d+\s+R)", pages[0])
    nums = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1))] if m else []
    if not nums:
        raise ValueError("the listing's page names no content stream")
    bad = [n for n in nums if n not in objs or objs[n][1] is None]
    if bad:
        raise ValueError(f"content stream(s) {bad} of the listing's page are missing or cannot be decoded")
    data = b"\n".join(objs[n][1] for n in nums)
    items: list[dict] = []
    P._run(data, items, 1)
    return items


def parse(pdf: bytes) -> list[dict]:
    """[{level, lake, counties, date}] from the listing; ValueError when no row is found."""
    items = page_items(pdf)
    rows: dict[float, list[dict]] = {}
    for it in items:
        if not it["text"].strip():
            continue
        y = next((k for k in rows if abs(k - it["y"]) <= 3), it["y"])
        rows.setdefault(y, []).append(it)
    out, level, seen, broken, said_empty = [], None, set(), [], set()
    counties_known = _nd_counties()
    for y in sorted(rows, reverse=True):
        cells = sorted(rows[y], key=lambda i: i["x"])
        line = "".join(c["text"] for c in cells).strip()
        low = re.sub(r"\s+", "", line).lower()
        if low in ("advisories", "advisory"):
            level = "advisory"
            seen.add(level)
            continue
        if low in ("warning", "warnings"):
            level = "warning"
            seen.add(level)
            continue
        if level is None or "lakename" in low or low in ("dateposted", "countydateposted"):
            continue
        if NONE_SAID.match(low):
            said_empty.add(level)
            continue
        lake = "".join(c["text"] for c in cells if c["x"] < 300).strip()
        county = "".join(c["text"] for c in cells if 300 <= c["x"] < 450).strip()
        dtext = "".join(c["text"] for c in cells if c["x"] >= 450).strip()
        m = DATE.match(re.sub(r"\s+", "", dtext))
        cs = [c.strip() for c in county.split("/") if c.strip()]
        if not lake or not m or not cs or any(c not in counties_known for c in cs):
            broken.append(line)     # not a whole lake, North Dakota county (or counties) and date: the read fails
            continue
        lake = re.sub(r"\s*-\s*", " - ", re.sub(r"\s+", " ", lake))
        out.append({"level": level, "lake": lake, "counties": cs,
                    "date": f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"})
    if seen != {"advisory", "warning"}:
        raise ValueError(f"the listing's tables were not all found (found: {sorted(seen) or 'none'})")
    if broken:
        raise ValueError(f"{len(broken)} row(s) of the listing could not be read whole: {broken[:3]}")
    empty = {"advisory", "warning"} - {x["level"] for x in out} - said_empty
    if empty:
        raise ValueError(f"no rows and no statement that the table is empty: {sorted(empty)}")
    return out          # both tables found, every row read whole, a table empty only where it says so


POINTS = Path(__file__).resolve().parents[2] / "data" / "reference" / "nd-hab-lake-points.json"


def lake_point(lake: str, counties: list[str]) -> dict | None:
    """The cited marker point of a listed lake (scripts/nd_hab_lake_points.py: inside the NHD waterbody of its GNIS name
    in a county DEQ lists), or None."""
    try:
        doc = json.loads(POINTS.read_text())
    except (OSError, ValueError):
        return None
    for r in doc.get("lakes") or []:
        if r["lake"] == lake and set(r["counties"]) == set(counties):
            return {"lat": r["lat"], "lon": r["lon"], "gnis_name": r["gnis_name"], "gnis_id": r["gnis_id"],
                    "county": r["county"], "basis": r["basis"],
                    "coord_source": r.get("coord_source") or "nhd_waterbody",
                    "source": r.get("source_url") or (doc.get("source") or {}).get("url")}
    return None


def zone_of(counties: list[str], lat=None, lon=None) -> tuple[str, str]:
    """The lake's zone: its point's side of the line in a split county (McKenzie, Sioux), else its counties'; Mountain
    if any county is (the later day's end)."""
    zs = [zones.north_dakota_zone(c, lat, lon) for c in counties] or [zones.north_dakota_zone(None, lat, lon)]
    mt = [z for z in zs if z[0] == zones.MOUNTAIN]
    return (mt or zs)[0]


def build(pdf: bytes, fetched: str, previous: list[dict], source_updated: str | None = None) -> tuple[list[dict], dict]:
    rows = parse(pdf)
    prev = {p["source_record_id"]: p for p in previous}
    out: dict[str, dict] = {}
    for x in rows:
        counties = sorted(x["counties"])
        base = (f"{slug(x['lake'])}:{'-'.join(slug(c) for c in counties) or 'no-county'}:{x['level']}:{x['date']}")
        # one record per observed period of a posting (re-review 2026-11-14 P2-1): the open one continues; a posting
        # that left the listing and comes back unchanged is a new period from the read that shows it again (precision
        # poll), so the gap stays a gap and the earlier period keeps its end
        periods = sorted((k for k in prev if k == base or k.startswith(base + "~")),
                         key=lambda k: int(k.rsplit("~", 1)[1]) if "~" in k else 1)
        open_ = [k for k in periods if prev[k].get("status") == "advisory_active"]
        srid = open_[-1] if open_ else (f"{base}~{len(periods) + 1}" if periods else base)
        returned = srid != base and srid not in prev
        old = prev.get(srid) or {}
        oraw = old.get("raw") or {}
        pt = lake_point(x["lake"], x["counties"])
        tz, basis = zone_of(x["counties"], *((pt["lat"], pt["lon"]) if pt else (None, None)))
        start = old.get("started_at") or (fetched if returned else x["date"])
        hist = list(oraw.get("_level_history") or [{"level": x["level"], "seen_at": fetched, "date": x["date"]}])
        raw = {"lake": x["lake"], "counties": x["counties"], "county": (x["counties"] or [None])[0],
               "level": x["level"], "level_meaning": LEVEL_MEANING[x["level"]], "date_posted": x["date"],
               "date_note": "DEQ's Date Posted: the day DEQ posted the advisory or warning; bloom onset and sampling "
                            "are not given",
               "time_zone": tz, "time_zone_basis": basis, "state": "ND", "listing_url": URL, "program_url": PAGE_URL,
               "placement_hint": {"name": x["lake"], "counties": x["counties"], "state": "ND",
                                  "basis": "the counties DEQ lists beside the lake: a same-named lake elsewhere in the "
                                           "state is not this one"},
               # DEQ lists the lake, not a beach or a station: the advisory colours the lake it is placed on, a large
               # one too, and keeps its marker where it has a point (build/status.py names_its_water; re-review
               # 2026-11-14 P1-1: a point-less advisory on a lake of 50 km2 or more was grey with no marker)
               "advisory_extent": "named_water",
               "_level_history": hist, "_first_seen_at": oraw.get("_first_seen_at") or fetched,
               "_last_seen_in_source": fetched}
        if returned or oraw.get("returned_after"):
            raw["returned_after"] = oraw.get("returned_after") or prev[periods[-1]]["raw"].get("_unlisted_since")
            raw["start_basis"] = ("DEQ's posting of " + x["date"] + " listed again after it had left the listing: this "
                                  "period starts at the first read that showed it again (DEQ gives no date for it)")
        if pt:
            raw["marker_point"] = pt
        if any(zones.north_dakota_zone_uncertain(c, *((pt["lat"], pt["lon"]) if pt else (None, None)))
               for c in x["counties"]):
            raw["time_zone_uncertain"] = True
        out[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory", status="advisory_active",
            waterbody_text=x["lake"], started_at=start, time_precision="poll" if "T" in start else "day",
            published_at=x["date"],
            lat=pt["lat"] if pt else None, lon=pt["lon"] if pt else None,
            coord_source=pt["coord_source"] if pt else None, coord_precision_m=100 if pt else None,
            source_updated_at=source_updated, fetched_at=fetched, authority=AUTHORITY,
            advice_text=LEVEL_MEANING[x["level"]], source_url=URL, raw=raw)
    lifted = 0
    for sid, p in prev.items():
        if sid in out:
            continue
        p = dict(p)
        raw = dict(p.get("raw") or {})
        if p.get("status") == "advisory_active":
            raw["_unlisted_since"] = fetched
            raw["ended_at_precision"] = "poll"
            raw["end_basis"] = ("the first read of DEQ's listing without this row; DEQ gives no lifting date, so the "
                                "read bounds the end")
            p["status"], p["ended_at"] = "advisory_lifted", fetched
            lifted += 1
        p["raw"] = raw
        out[sid] = p
    recs = sorted(out.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "listed": len(rows),
            "advisories": sum(1 for x in rows if x["level"] == "advisory"),
            "warnings": sum(1 for x in rows if x["level"] == "warning"), "lifted_this_read": lifted,
            "advisory_active": sum(1 for r in recs if r["status"] == "advisory_active"),
            "cadence": "the listing read every run; DEQ updates it from 1 May to 31 December",
            "credit": "North Dakota Department of Environmental Quality, harmful algal bloom listing",
            "caveat": ("DEQ's list of the advisories and warnings it has posted for publicly accessible waters it "
                       "monitors; a water not listed is not a water found free of blooms.")}
    return recs, meta


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    updated = None
    try:
        if "--file" in argv:
            pdf = Path(argv[argv.index("--file") + 1]).read_bytes()
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(20, 120))
            r.raise_for_status()
            pdf = r.content
            save_raw(SOURCE_ID, pdf, "pdf")              # DEQ's public list: it names no person
            if r.headers.get("Last-Modified"):
                updated = parsedate_to_datetime(r.headers["Last-Modified"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        recs, meta = build(pdf, fetched, prev, updated)
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['advisories']} advisories and {meta['warnings']} warnings listed, {len(recs)} records "
          f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
