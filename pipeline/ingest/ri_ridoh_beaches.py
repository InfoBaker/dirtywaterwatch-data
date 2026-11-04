"""RIDOH beach closures (Rhode Island): the Google Sheet behind https://health.ri.gov/beaches.

Source: spreadsheet 1KXdH37xHUPrjJSEkryquPQ2GaP-R_9Gl5NkZrUnAjjU read as CSV through the public
Google Visualization endpoint (no auth): gid 828265472 is the current season's list the beaches page
draws (Beach, City/Town, Closed On, Re-Opened, Number of Days Closed, FW or SW); gid 29002208 is the
history tab, 2000 to the last finished season (~1,100 rows), read with --backfill.
Coordinates come from RIDOH's own beach layer RIDOHGIS_Beaches_View (layer 0 points, joined to
table 5 MasterList for town names), matched by beach name and town; cached in
data/raw/ri-ridoh-beaches/ and refreshed every 30 days.

Record rules:
- One beach_closure record per row; rows the sheet marks "(Cyanobacteria Advisory)" or "(for
  bluegreen algae)" are hab_advisory. Cause is never inferred: the sheet gives none for the others,
  so material is null. An empty Re-Opened means still closed (status advisory_active) for the
  current tab and for rows of the current year; on the history tab, earlier seasons often leave
  Re-Opened blank (2022-2025), so those rows end at Closed On + Number of Days Closed when the
  number is given (raw.ended_at_basis says so) and are status unknown when it is not.
- Dates are day precision at 00:00 America/New_York. Obvious year typos (re-opened "8/7/2027" for a
  2-day closure from 8/5/2026) are corrected only when Number of Days Closed confirms the
  correction; the original is kept in raw.corrections. Two-digit years ("7/8/19") are read as 20xx.
- event_id = ri-ridoh-beaches:<beach>:<town>:<closed date>. Rows seen earlier and no longer in the
  sheet are kept (the current tab is cleared each season).
- water_slugs: the openboatlaunch water named in the beach name when one lies within 1 km
  (water_match "name"); otherwise the only water within 300 m of the beach point, or the nearest
  when it is less than half as far as the next (water_match "geometry"); otherwise none.

Quirks: the sheet is an informal back end (RIDOH may change key or sharing); town typos ("Wawick");
the gviz CSV adds blank columns; results are not published, only closures.

Cadence: daily from Memorial Day to Labor Day (monitoring ended 2026-09-23); weekly otherwise.

Run: python -m ingest.ri_ridoh_beaches [--backfill]   (from pipeline/)
"""
from __future__ import annotations

import csv
import io
import re
import sys
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, RAW_DIR, event, now_iso, path_notes_to_meta, read_json, save_raw, write_events, write_json
from ingest import ri_waters

SOURCE_ID = "ri-ridoh-beaches"
KEY = "1KXdH37xHUPrjJSEkryquPQ2GaP-R_9Gl5NkZrUnAjjU"
GIDS = {"current": "828265472", "history": "29002208"}
SHEET_URL = "https://docs.google.com/spreadsheets/d/{key}/gviz/tq?tqx=out:csv&gid={gid}"
PAGE_URL = "https://health.ri.gov/beaches"
BV = "https://services1.arcgis.com/dkWT1XL4nglP5MLP/arcgis/rest/services/RIDOHGIS_Beaches_View/FeatureServer"
BV_CACHE = RAW_DIR / SOURCE_ID / "ridohgis-beaches-view.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Rhode Island Department of Health (RIDOH) Beach Monitoring Program"
HAB_RE = re.compile(r"cyanobacteri|blue\s*-?\s*green\s+alga", re.I)
GENERIC = {"beach", "the", "swim", "area", "at", "and", "of"}
VILLAGES = {
    "saunderstown": "north kingstown", "wickford": "north kingstown", "chepachet": "glocester",
    "greenville": "smithfield", "wakefield": "south kingstown", "kingston": "south kingstown",
    "west kingston": "south kingstown", "peace dale": "south kingstown", "matunuck": "south kingstown",
    "harrisville": "burrillville", "pascoag": "burrillville", "hope valley": "hopkinton",
    "wyoming": "richmond", "block island": "new shoreham", "rumford": "east providence",
    "riverside": "east providence", "misquamicut": "westerly", "watch hill": "westerly",
    "weekapaug": "westerly", "quonochontaug": "charlestown", "galilee": "narragansett",
    "slatersville": "north smithfield", "forestdale": "north smithfield", "manville": "lincoln",
    "greene": "coventry", "hope": "scituate", "north scituate": "scituate", "apponaug": "warwick",
    "prudence island": "portsmouth", "jamestown": "jamestown",
}


# ---------------------------------------------------------------- helpers

def clean_name(s: str) -> str:
    """'Governor Notte Park Beach (Cyanobacteria Advisory)' -> 'Governor Notte Park Beach'."""
    s = re.sub(r"\([^)]*(?:cyanobacteri|blue\s*-?\s*green)[^)]*\)", "", s or "", flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" ,-")


def tokens(s: str) -> list[str]:
    s = re.sub(r"\([^)]*\)", " ", s or "")
    s = re.sub(r"'s\b", "", s.replace("’", "'"))
    return [t for t in ri_waters.norm(s).split() if t not in GENERIC]


def towns_of(s: str) -> set[str]:
    out = set()
    for part in re.split(r"[/,&]", s or ""):
        t = ri_waters.norm_town(part)
        if t:
            out.add(VILLAGES.get(t, t))
    return out


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ri_waters.norm(s))).strip("-") or "x"


def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unparsed date {s!r}")


def day_iso(d: date | None) -> str | None:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat() if d else None


def metres(lat1, lon1, lat2, lon2) -> float:
    return (((lat1 - lat2) * ri_waters.MY) ** 2 + ((lon1 - lon2) * ri_waters.MX) ** 2) ** 0.5


# ---------------------------------------------------------------- RIDOH beach layer

def load_beaches(session: requests.Session) -> list[dict]:
    cached = read_json(BV_CACHE)
    fresh = cached and datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00")) > datetime.now(UTC) - timedelta(days=30)
    if not fresh:
        try:
            q = {"where": "1=1", "outFields": "*", "outSR": 4326, "f": "json", "resultRecordCount": 2000}
            pts = session.get(f"{BV}/0/query", params=q, timeout=60).json()
            ml = session.get(f"{BV}/5/query", params={**q, "outSR": None}, timeout=60).json()
            if "features" not in pts or "features" not in ml:
                raise ValueError(str(pts)[:200])
            cached = {"fetched_at": now_iso(), "url": BV, "points": pts["features"], "masterlist": ml["features"]}
            write_json(BV_CACHE, cached)
        except Exception as e:
            print(f"ri-ridoh-beaches: beach layer unavailable ({e}); no coordinates this run", file=sys.stderr)
            if not cached:
                return []
    master = {f["attributes"]["BeachID"]: f["attributes"] for f in cached.get("masterlist", [])}
    code_town = {}
    for f in cached["points"]:  # layer 0 codes towns as integers; MasterList names them
        a = f["attributes"]
        m = master.get(a.get("BeachID"))
        if m and m.get("Town"):
            code_town.setdefault(a.get("Town"), m["Town"])
    out = []
    for f in cached["points"]:
        a, g = f["attributes"], f.get("geometry") or {}
        lat, lon = g.get("y", a.get("PointY")), g.get("x", a.get("PointX"))
        if lat is None or lon is None or not a.get("NAME"):
            continue
        town = (master.get(a.get("BeachID")) or {}).get("Town") or code_town.get(a.get("Town"))
        out.append({"name": a["NAME"].strip(), "beach_id": a.get("BeachID"), "town": town, "lat": lat, "lon": lon,
                    "tokens": tokens(a["NAME"]), "town_n": ri_waters.norm_town(town) if town else None})
    return out


def match_beach(name: str, town: str, beaches: list[dict]) -> tuple[list[dict], str | None]:
    """Sheet beach -> RIDOH layer point(s) and how. Several points come back only when they are one
    place (e.g. Kent County YMCA upper and lower ponds)."""
    tk = tokens(clean_name(name))
    if not tk:
        return [], None
    towns = towns_of(town)
    local = [b for b in beaches if b["town_n"] in towns] if towns else []
    for pool, where in ((local, "same town"), (beaches, "any town")):
        if not pool:
            continue
        exact = [b for b in pool if b["tokens"] == tk]
        if exact:
            return exact, f"name ({where})"
        sub = [b for b in pool if set(tk) <= set(b["tokens"]) or (set(b["tokens"]) <= set(tk) and len(b["tokens"]) >= 2)]
        if sub and where == "same town":
            return sub, f"name tokens ({where})"
        if where == "same town":
            s = " ".join(tk)
            scored = sorted(((SequenceMatcher(None, s, " ".join(b["tokens"])).ratio(), b) for b in pool),
                            key=lambda t: -t[0])
            if scored and scored[0][0] >= 0.8 and scored[0][1]["tokens"][:1] and \
                    SequenceMatcher(None, tk[0], scored[0][1]["tokens"][0]).ratio() >= 0.8:
                best = scored[0][0]
                return [b for r, b in scored if r >= best - 0.02], f"fuzzy name {best:.2f} ({where})"
    return [], None


def place(cands: list[dict]) -> tuple[float | None, float | None, int | None, list]:
    if not cands:
        return None, None, None, []
    lat = sum(c["lat"] for c in cands) / len(cands)
    lon = sum(c["lon"] for c in cands) / len(cands)
    spread = max(metres(lat, lon, c["lat"], c["lon"]) for c in cands)
    if spread > 1500:
        return None, None, None, cands  # different places: ambiguous
    return lat, lon, (int(round(spread)) or None), cands


def waters_for(name: str, town: str, lat, lon) -> tuple[list[str], str, dict]:
    if lat is None:
        return [], "none", {}
    near = ri_waters.near(lat, lon, 1000)
    btoks = set(tokens(clean_name(name)))
    ttoks = set(ri_waters.norm(town).split())  # "Warren Town Beach" names the town, not the Warren River
    named = [s for s, d in near if ri_waters.water_words(s) and ri_waters.water_words(s) <= btoks
             and not ri_waters.water_words(s) <= ttoks]
    if named:
        return named[:1], "name", {"nearest_waters_m": near[:3]}
    close = [(s, d) for s, d in near if d <= 300]
    if len(close) == 1 or (len(close) > 1 and close[0][1] * 2 < close[1][1]):
        return [close[0][0]], "geometry", {"nearest_waters_m": near[:3]}
    return [], "none", {"nearest_waters_m": near[:3], "ambiguous": len(close) > 1}


# ---------------------------------------------------------------- rows -> records

def fetch_sheet(session: requests.Session, which: str) -> tuple[list[dict], str]:
    url = SHEET_URL.format(key=KEY, gid=GIDS[which])
    r = session.get(url, timeout=60)
    r.raise_for_status()
    if "text/csv" not in r.headers.get("Content-Type", "") and r.text.lstrip().startswith("<"):
        raise ValueError(f"{which} sheet did not return CSV (sharing changed?)")
    save_raw(SOURCE_ID, r.content, f"{which}.csv")
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(r.text))):
        rows.append(row)
    if not rows or "Beach" not in rows[0][0]:
        raise ValueError(f"{which} sheet header changed: {rows[:1]}")
    head = [h.strip() for h in rows[0]]
    out = []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        rec = {head[i] or f"col{i + 1}": row[i] for i in range(min(len(head), len(row)))}
        rec = {k: v for k, v in rec.items() if not (k.startswith("col") and not v.strip())}
        out.append({"sheet": which, "row": n, "cells": rec})
    return out, url


def row_to_record(item: dict, url: str, beaches: list[dict], today: date, fetched: str) -> dict:
    c = item["cells"]
    beach = (c.get("Beach") or "").strip()
    town = (c.get("City/Town") or "").strip()
    raw = {"sheet": item["sheet"], "sheet_row": item["row"], "sheet_url": url, **{k: v for k, v in c.items()}}
    corrections, parse_error = [], None
    days = None
    try:
        days = int(float(c.get("Number of Days Closed", "").strip())) if (c.get("Number of Days Closed") or "").strip() else None
    except ValueError:
        corrections.append(f"Number of Days Closed not a number: {c.get('Number of Days Closed')!r}")
    try:
        closed = parse_date(c.get("Closed On"))
    except ValueError as e:
        closed, parse_error = None, str(e)
    try:
        reopened = parse_date(c.get("Re-Opened"))
    except ValueError as e:
        reopened, parse_error = None, (parse_error + "; " if parse_error else "") + str(e)
    if closed and reopened and (reopened - closed).days > 300 and days is not None:
        for fix in (reopened.replace(year=closed.year), ):
            if (fix - closed).days == days:
                corrections.append(f"Re-Opened {c.get('Re-Opened')!r} read as {fix:%-m/%-d/%Y} (Number of Days Closed = {days})")
                reopened = fix
    if closed and reopened and reopened < closed:
        parse_error = (parse_error + "; " if parse_error else "") + "Re-Opened is before Closed On"
    hab = bool(HAB_RE.search(beach))
    ended, basis = reopened, None
    if closed is None:
        status = "unknown"
    elif reopened:
        status = "advisory_lifted"
    elif item["sheet"] == "current" or closed.year >= today.year:
        status = "advisory_active"
        if (today - closed).days > 60:
            raw["note"] = (f"still open in the sheet {(today - closed).days} days after closing; "
                           "RIDOH may not have recorded the re-opening")
    elif days is not None:
        ended, basis, status = closed + timedelta(days=days), "Closed On + Number of Days Closed (Re-Opened blank)", "advisory_lifted"
    else:
        status = "unknown"
        raw["note"] = "earlier season with Re-Opened and Number of Days Closed blank; end not recorded"
    if basis:
        raw["ended_at_basis"] = basis
    if corrections:
        raw["corrections"] = corrections

    cands, how = match_beach(beach, town, beaches)
    lat, lon, spread, used = place(cands)
    raw["coord_join"] = {"layer": f"{BV}/0", "how": how if lat is not None else (how and "ambiguous"),
                         "matched": [{"name": b["name"], "beach_id": b["beach_id"], "town": b["town"]} for b in used]} if cands else None
    slugs, wmatch, wdetail = waters_for(beach, town, lat, lon)
    raw["water_placement"] = wdetail or None

    rid = f"{slugify(clean_name(beach))}:{slugify(VILLAGES.get(ri_waters.norm_town(town), ri_waters.norm_town(town)) or 'na')}:{closed.isoformat() if closed else 'row' + str(item['row'])}"
    return event(
        source_id=SOURCE_ID, source_record_id=rid,
        event_type="unknown" if parse_error and not closed else ("hab_advisory" if hab else "beach_closure"),
        status=status,
        waterbody_text=f"{clean_name(beach)} ({town})" if town else clean_name(beach),
        water_slugs=slugs, water_match=wmatch,
        lat=round(lat, 6) if lat is not None else None, lon=round(lon, 6) if lon is not None else None,
        coord_source="source" if lat is not None else None, coord_precision_m=spread,
        started_at=day_iso(closed), ended_at=day_iso(ended), time_precision="day",
        fetched_at=fetched, authority=AUTHORITY, source_url=PAGE_URL, raw=raw, parse_error=parse_error,
    )


def main(argv: list[str]) -> int:
    backfill = "--backfill" in argv
    s = requests.Session()
    s.headers.update(HEADERS)
    fetched = now_iso()
    today = datetime.now(TZ).date()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    items, urls, errors = [], {}, []
    for which in (["history"] if backfill else []) + ["current"]:
        try:
            rows, url = fetch_sheet(s, which)
            items += rows
            urls[which] = url
        except Exception as e:
            errors.append(f"{which}: {e}")
    if "current" not in urls:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(errors))
        print(f"ri-ridoh-beaches: FAILED {errors}", file=sys.stderr)
        return 1
    beaches = load_beaches(s)
    records, seen = {}, {}
    for it in items:  # history first, then current: current wins on the same event id
        rec = row_to_record(it, urls[it["sheet"]], beaches, today, fetched)
        k = rec["event_id"]
        seen[(it["sheet"], k)] = seen.get((it["sheet"], k), 0) + 1
        if seen[(it["sheet"], k)] > 1:  # the same beach closed twice on one day in one tab
            rec["event_id"] = f"{k}-{seen[(it['sheet'], k)]}"
            rec["source_record_id"] = rec["event_id"].split(":", 1)[1]
        records[rec["event_id"]] = rec
    kept = 0
    for r in prev:  # rows no longer in the sheet stay as history
        if r["event_id"] not in records:
            records[r["event_id"]] = r
            kept += 1
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {
        "rows_read": len(items), "backfill": backfill, "kept_from_previous": kept, "beach_points": len(beaches),
        "with_coords": sum(1 for r in out if r["lat"] is not None),
        "with_water_slug": sum(1 for r in out if r["water_slugs"]),
        "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
        "hab_advisory": sum(1 for r in out if r["event_type"] == "hab_advisory"),
        "parse_errors": sum(1 for r in out if r["parse_error"]),
        "sheet_errors": errors or None,
    }
    path_notes_to_meta(out, meta)          # notes naming repository files stay out of raw
    path = write_events(SOURCE_ID, out, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"ri-ridoh-beaches: {len(out)} records ({meta['advisory_active']} active, {meta['hab_advisory']} HAB); "
          f"coords {meta['with_coords']}, water slug {meta['with_water_slug']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
