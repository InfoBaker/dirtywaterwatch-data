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
  Lake Washington") are joined. A file with no row read writes ok=False and the previous records stay.

Record rules
  - One hab_advisory record per lake and county set per season: source_record_id <year of the date>:<lake>:<counties>
    (DEQ gives no row id). raw.level "advisory" or "warning" (the table the row is in); a lake moved from one table to
    the other keeps its record, with the change in raw._level_history.
  - started_at: the Date Posted, precision day, DEQ's own posting of the advisory or warning (raw.date_note); bloom
    onset and sampling are not given. published_at the same day. source_updated_at the file's Last-Modified time.
  - Status: advisory_active while the row is listed (raw._last_seen_in_source each read: DEQ's own window, red); the
    first read without the row ends it: advisory_lifted, ended_at that read's time, raw.ended_at_precision "poll"
    (DEQ gives no lifting date; the read bounds it) and raw._unlisted_since. A row that comes back reopens the record.
    A file that cannot be read never ends anything.
  - Clock: raw.time_zone from the county (pipeline/zones.py north_dakota_zone, 49 CFR 71.7(a)): Mountain for the
    southwestern counties (Lake Tschida in Grant County, Bowman-Haley Dam in Bowman County, Patterson Lake in Stark
    County, Lake Ilo in Dunn County), Central elsewhere; a county set read in Mountain time if any county is.
  - Place: no coordinates. Placed by the lake's name, county-aware: raw.county the first county DEQ gives (the status
    build's COUNTY_FIELD_STATES), raw.counties all of them, raw.placement_hint {name, counties, state}. A lake with no
    water record is listed in research/nd/receiving-waters-missing.json with its counties.
  - Privacy: lake, county and date only; the listing names no person.

Run from pipeline/:  python -m ingest.nd_deq_hab_listings [--file saved.pdf]
"""
from __future__ import annotations

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


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def page_items(pdf: bytes) -> list[dict]:
    """Positioned text of the first page, its content streams joined in the page's /Contents order (a cell cut between
    two streams is read whole); falls back to nh_pdftext.text_items when the page names no /Contents array."""
    objs = P._streams(pdf)
    m = re.search(rb"/Contents\s*\[([^\]]*)\]", pdf)
    nums = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1))] if m else []
    if not nums:
        nums = [int(x) for x in re.findall(rb"/Contents\s+(\d+)\s+\d+\s+R", pdf)[:1]]
    if not nums:
        return P.text_items(pdf)
    data = b"\n".join(objs[n][1] or b"" for n in nums if n in objs)
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
    out, level = [], None
    for y in sorted(rows, reverse=True):
        cells = sorted(rows[y], key=lambda i: i["x"])
        line = "".join(c["text"] for c in cells).strip()
        low = re.sub(r"\s+", "", line).lower()
        if low in ("advisories", "advisory"):
            level = "advisory"
            continue
        if low in ("warning", "warnings"):
            level = "warning"
            continue
        if level is None or "lakename" in low:
            continue
        lake = "".join(c["text"] for c in cells if c["x"] < 300).strip()
        county = "".join(c["text"] for c in cells if 300 <= c["x"] < 450).strip()
        dtext = "".join(c["text"] for c in cells if c["x"] >= 450).strip()
        m = DATE.match(re.sub(r"\s+", "", dtext))
        if not lake or not m:
            continue
        lake = re.sub(r"\s*-\s*", " - ", re.sub(r"\s+", " ", lake))
        out.append({"level": level, "lake": lake, "counties": [c.strip() for c in county.split("/") if c.strip()],
                    "date": f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"})
    if not out:
        raise ValueError("no advisory or warning row read from the listing")
    return out


def zone_of(counties: list[str]) -> tuple[str, str]:
    zs = [zones.north_dakota_zone(c) for c in counties] or [zones.north_dakota_zone(None)]
    mt = [z for z in zs if z[0] == zones.MOUNTAIN]
    return (mt or zs)[0]


def build(pdf: bytes, fetched: str, previous: list[dict], source_updated: str | None = None) -> tuple[list[dict], dict]:
    rows = parse(pdf)
    prev = {p["source_record_id"]: p for p in previous}
    out: dict[str, dict] = {}
    for x in rows:
        srid = f"{x['date'][:4]}:{slug(x['lake'])}:{'-'.join(slug(c) for c in x['counties']) or 'no-county'}"
        if srid in out:                       # the same lake in both tables: the warning, the later posting, wins
            if out[srid]["raw"]["level"] == "warning":
                continue
        old = prev.get(srid) or {}
        oraw = old.get("raw") or {}
        tz, basis = zone_of(x["counties"])
        start = min(x["date"], old.get("started_at") or x["date"])
        hist = list(oraw.get("_level_history") or [{"level": x["level"], "seen_at": fetched, "date": x["date"]}])
        if hist[-1]["level"] != x["level"]:
            hist.append({"level": x["level"], "seen_at": fetched, "date": x["date"]})
        raw = {"lake": x["lake"], "counties": x["counties"], "county": (x["counties"] or [None])[0],
               "level": x["level"], "level_meaning": LEVEL_MEANING[x["level"]], "date_posted": x["date"],
               "date_note": "DEQ's Date Posted: the day DEQ posted the advisory or warning; bloom onset and sampling "
                            "are not given",
               "time_zone": tz, "time_zone_basis": basis, "state": "ND", "listing_url": URL, "program_url": PAGE_URL,
               "placement_hint": {"name": x["lake"], "counties": x["counties"], "state": "ND",
                                  "basis": "the counties DEQ lists beside the lake: a same-named lake elsewhere in the "
                                           "state is not this one"},
               "_level_history": hist, "_first_seen_at": oraw.get("_first_seen_at") or fetched,
               "_last_seen_in_source": fetched}
        if oraw.get("_unlisted_since"):
            raw["_absences"] = list(oraw.get("_absences") or []) + [{"from": oraw["_unlisted_since"], "to": fetched}]
        out[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory", status="advisory_active",
            waterbody_text=x["lake"], started_at=start, time_precision="day", published_at=x["date"],
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
