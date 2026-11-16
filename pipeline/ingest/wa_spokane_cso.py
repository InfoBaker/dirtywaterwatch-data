"""City of Spokane's real-time CSO table -> data/build/events/wa-spokane-cso-update.json.

Source (register row WA:wa-spokane-cso-public-notification; data/sources/wa-spokane-cso-update.yaml)
  "Real Time Combined Sewer Overflow Monitoring", https://sewerfinder.spokanecity.org/CSOUpdate (an ASP.NET page; 200
  to GitHub's runner, probes 43899088975 and 43982578840 of 2026-11-16; this Mac meets a 403). The page says: "As of
  January 1, 2023 there are 20 monitoring sites. If a site is flashing, that represents that a CSO overflow event is
  occurring or has occurred in the last 48 hours. The date and time listed is the start time of the overflow event and
  will automatically shut off after 48 hours." One table (id MainContent_CSOGridView), header CSO # | OUTFALL LOCATION |
  STATUS | OVERFLOW DATE & TIME, one row per site: "CSO2" ... "CSO42", "CSO23-1", "CSO33-2", "RPWRF Bypass" (the
  treatment plant's bypass), a location ("0.6 miles downstream of RPWRF") with a map link, a status (IS in service, OS
  out of service, N/A not available) and the overflow start or "none". The page names no receiving water and gives no
  end and no volume. On 2026-11-16 every site read "none"; no capture with an overflow was found (the Internet
  Archive holds one, of 2022-01-21, also "none"), so the start's format was never seen: the reader takes a US date with
  a 12- or 24-hour time (DATE_FORMATS) and any other text is an unread row (health false), never "none".

Records (a status page read hourly; records build up from the reads, as oh_lakewood_cso does)
  - One per site and start: source_record_id "<site slug>:<start, local YYYYMMDDTHHMM>". started_at the start as
    given; ended_at null and status unknown (end not confirmed): the page shows an overflow for 48 hours from its start
    whether or not it has ended, so neither its presence nor its disappearance is an end (raw.end_note). The record
    stays when the page drops it (raw._left_page_at): a past report. A start seen again keeps one record.
  - event_type cso; "RPWRF Bypass" (Riverside Park Water Reclamation Facility) is plant_bypass.
  - Times: local wall-clock with no zone; Spokane is in Washington, Pacific time: America/Los_Angeles (a time in the
    spring-forward gap is not read; a repeated hour is read as its first occurrence). published_at and
    source_updated_at null (the page gives no posting or update time); fetched_at and raw._last_seen_in_source the last
    read that showed the start; raw._first_seen_at the first.
  - Place: permit WA0024473 (City of Spokane; data/dischargers.json wa-spokane). A site named "CSO<n>" is tied to the
    registry's outfall n of that permit only when exactly that number is an open CSO outfall with its own point
    (permitted feature): outfall_id, the registry's point and its water (the page names none; raw.water_basis). A
    suffixed site ("CSO23-1", "CSO33-2") is not outfall 023 or 033, and the bypass is not a CSO outfall: no outfall,
    point or water. The page's map links are never used for a point.
  - A site whose status is OS or N/A has no working monitor: its "none" is no evidence (meta.sites_not_in_service).
State: data/build/wa-spokane-cso-state.json (every start seen; the archive). Do not delete it.
Failures: a failed request, a page without the table or with another header, fewer than MIN_ROWS rows or more than
  DROP_ALLOWED fewer than the last read (truncated): a failed read (ok=False, the previous records kept, the state
  unchanged). A row whose status or date the reader does not know is unread: the other rows are read and health stays
  false until it reads.
History: the page keeps an overflow 48 hours and has no archive: no --backfill (the flag is accepted and does nothing
  more). The hourly read is the history.
Run from pipeline/: python -m ingest.wa_spokane_cso [--file saved.html ... --out events.json]
Cadence: hourly with the refresh (Washington is live).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, HEADERS, event, load_outfall_registry, now_iso, outfall_number, read_json, save_raw,
                    write_events, write_json)
from ingest.oh_cso_pdf_notices import existing

SOURCE_ID = "wa-spokane-cso-update"
URL = "https://sewerfinder.spokanecity.org/CSOUpdate"
TZ_NAME = "America/Los_Angeles"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "WA0024473"
DISCHARGER = "City of Spokane"
DISCHARGER_ID = "wa-spokane"
STATE_PATH = BUILD_DIR / "wa-spokane-cso-state.json"
CREDIT = "City of Spokane, Real Time Combined Sewer Overflow Monitoring"
MATERIAL = "combined sewage and stormwater"
HEADER = ["CSO #", "OUTFALL LOCATION", "STATUS", "OVERFLOW DATE & TIME"]
STATUSES = {"IS", "OS", "N/A"}
MIN_ROWS = 15            # 20 sites on 2026-11-16
DROP_ALLOWED = 3
TABLE = re.compile(r'<table[^>]*id="MainContent_CSOGridView"[^>]*>(.*?)</table>', re.S | re.I)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t([dh])[^>]*>(.*?)</t[dh]>", re.S | re.I)
DATE_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M")


class LayoutError(ValueError):
    """The page has no table this reader knows: a failed read, never "no overflows"."""


def clean(v: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", v or "")).replace("\xa0", " ").split())


def local(v: str | None) -> datetime | None:
    s = " ".join((v or "").split()).upper()
    for f in DATE_FORMATS:
        try:
            t = datetime.strptime(s, f)
        except ValueError:
            continue
        return existing(t.replace(tzinfo=TZ))
    return None


def slug(site: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", site.lower()).strip("-")


def parse(page: str) -> tuple[list[dict], list[str]]:
    """(rows read, rows not read with the reason). Raises LayoutError when the table is missing or changed."""
    m = TABLE.search(page or "")
    if not m:
        raise LayoutError("no CSO table (MainContent_CSOGridView) on the page")
    trs = ROW.findall(m.group(1))
    if not trs:
        raise LayoutError("the CSO table has no rows")
    head = [clean(c) for _, c in CELL.findall(trs[0])]
    if head != HEADER:
        raise LayoutError(f"the table's header is {head}, not {HEADER}")
    rows, unread = [], []
    for n, tr in enumerate(trs[1:], 1):
        cells = CELL.findall(tr)
        if len(cells) != 4 or any(k != "d" for k, _ in cells):
            unread.append(f"row {n}: {len(cells)} cells")
            continue
        raw_site = cells[0][1]
        site, loc, status, when = (clean(c) for _, c in cells)
        img = re.search(r'src="([^"]+)"', raw_site)
        site = site.replace("*", "").strip()
        star = "*" in clean(cells[0][1])
        bad = []
        if not site:
            bad.append("no site name")
        if status not in STATUSES:
            bad.append(f"status '{status[:20]}'")
        start = None
        if when.lower() != "none":
            start = local(when)
            if start is None:
                bad.append(f"overflow date '{when[:40]}' not read")
        if bad:
            unread.append(f"{site or 'row ' + str(n)}: " + ", ".join(bad))
            continue
        rows.append({"site": site, "location": re.sub(r"\s*Map$", "", loc).strip(), "status": status,
                     "start": start.isoformat() if start else None, "start_text": None if start is None else when,
                     "image": img.group(1).rsplit("/", 1)[-1] if img else None, "not_storm_related": star})
    if not rows and not unread:
        raise LayoutError("the CSO table has no site row")
    return rows, unread


def complete(n: int, state_path: Path) -> None:
    prev = ((read_json(state_path, {}) or {}).get("last_poll") or {}).get("rows") or 0
    if n < MIN_ROWS or n < prev - DROP_ALLOWED:
        raise LayoutError(f"{n} site rows on the page (the last read had {prev}): the page looks truncated")


def poll(state: dict, rows: list[dict], now: str) -> dict:
    evs = state.setdefault("events", {})
    sites = state.setdefault("sites", {})
    counts = {"opened": 0, "seen": 0, "left": 0}
    shown = set()
    for r in rows:
        sites[r["site"]] = {"location": r["location"], "status": r["status"], "last_read_at": now}
        if not r["start"]:
            continue
        st = datetime.fromisoformat(r["start"])
        key = f"{slug(r['site'])}:{st.strftime('%Y%m%dT%H%M')}"
        shown.add(key)
        cur = evs.get(key)
        if cur is None:
            cur = evs[key] = {"site": r["site"], "start": r["start"], "start_text": r["start_text"], "first_seen_at": now}
            counts["opened"] += 1
        else:
            counts["seen"] += 1
            cur.pop("left_page_at", None)
        cur.update(last_seen_at=now, location=r["location"], status=r["status"], image=r["image"],
                   not_storm_related=r["not_storm_related"])
    read = {r["site"] for r in rows}          # only a site read this time can have left (an unread row is no evidence)
    for key, ev in evs.items():
        if key not in shown and ev["site"] in read and not ev.get("left_page_at"):
            ev["left_page_at"] = now
            counts["left"] += 1
    return counts


def outfall_points(rows: list[dict]) -> dict[str, dict]:
    """Spokane's open CSO outfalls in the registry with their own point, by outfall number."""
    out = {}
    for r in rows:
        if r.get("npdes_permit") != PERMIT or r.get("outfall_kind") != "cso" or r.get("lat") is None:
            continue
        if str(r.get("outfall_status") or "").upper().startswith("CLS") or r.get("coords_from") != "permitted_feature":
            continue
        out[outfall_number(r.get("outfall"))] = r
    return out


def tie(site: str, points: dict[str, dict]) -> tuple[dict | None, str]:
    m = re.fullmatch(r"CSO\s*(\d{1,3})", site.strip(), re.I)
    o = points.get(outfall_number(m.group(1))) if m else None
    if o:
        return o, f"site {site} is registry outfall {o['outfall']} of {PERMIT}"
    if re.fullmatch(r"CSO\s*\d{1,3}-\d+", site.strip(), re.I):
        return None, (f"site {site} is a numbered part of an outfall, not an outfall number in the registry for {PERMIT}: "
                      "no outfall, point or water tied")
    return None, (f"site {site} is not an open combined sewer outfall of {PERMIT} with its own point in the registry: "
                  "no outfall, point or water tied")


def to_record(key: str, ev: dict, points: dict[str, dict]) -> dict:
    o, basis = tie(ev["site"], points)
    bypass = "bypass" in ev["site"].lower()
    raw = {"site": ev["site"], "location": ev.get("location"), "site_status": ev.get("status"),
           "start_as_written": ev.get("start_text"), "image": ev.get("image"), "time_zone": TZ_NAME, "state": "WA",
           "_first_seen_at": ev["first_seen_at"], "_last_seen_in_source": ev["last_seen_at"],
           "time_note": "the page writes local times with no zone; Spokane is in Washington: read as America/Los_Angeles",
           "end_note": ("the page gives only the start and shows an overflow for 48 hours from it, whether or not it "
                        "has ended: end not confirmed"),
           "place_basis": basis}
    if o:
        raw["water_basis"] = (f"the page names no receiving water; the registry's outfall {o['outfall']} of {PERMIT} "
                              f"is on {o.get('water_name')}")
    if ev.get("left_page_at"):
        raw["_left_page_at"] = ev["left_page_at"]
    if ev.get("not_storm_related"):
        raw["note"] = "the page marks this site: \"This outfall is not storm related\""
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="plant_bypass" if bypass else "cso", status="unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=PERMIT,
        outfall_id=o["outfall"] if o else None, outfall_name=ev["site"],
        waterbody_text=o.get("water_name") if o else None,
        lat=o["lat"] if o else None, lon=o["lon"] if o else None, coord_source="outfall_layer" if o else None,
        started_at=ev["start"], ended_at=None, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=ev["last_seen_at"],
        material="sewage" if bypass else MATERIAL, volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=CREDIT, advice_text=None, source_url=URL, raw=raw)


def run(rows: list[dict], now: str, state_path: Path, registry: list[dict] | None = None) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    counts = poll(state, rows, now)
    state["last_poll"] = {"at": now, "rows": len(rows), **counts}
    write_json(state_path, state)
    points = outfall_points(registry if registry is not None else load_outfall_registry())
    recs = [to_record(k, ev, points) for k, ev in state["events"].items()]
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    out_of_service = sorted(s for s, v in state["sites"].items() if v.get("status") != "IS")
    return recs, {"registry_ids": [SOURCE_ID], "url": URL, "poll": state["last_poll"], "credit": CREDIT,
                  "sites": len(state["sites"]), "sites_not_in_service": out_of_service,
                  "tied_outfalls": sorted(points), "covers_permits": [PERMIT], "time_zone": TZ_NAME}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", help="saved pages, read in order as successive polls (needs --out)")
    ap.add_argument("--out")
    ap.add_argument("--backfill", action="store_true", help="accepted for the refresh; the page has no archive")
    a = ap.parse_args(argv)
    if a.file and not a.out:
        ap.error("--file needs --out")
    out = Path(a.out) if a.out else None
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    try:
        if a.file:
            pages = [Path(f).read_text(errors="replace") for f in a.file]
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(20, 90))
            r.raise_for_status()
            pages = [r.text]
        parsed = [parse(p) for p in pages]
        for rows, unread in parsed:
            complete(len(rows) + len(unread), state_path)
    except (requests.RequestException, LayoutError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    recs, meta, unread = [], {}, []
    for rows, unread in parsed:
        if not a.file:
            save_raw(SOURCE_ID, json.dumps(rows), "json")        # the parsed rows only
        recs, meta = run(rows, now_iso(), state_path)
    if unread:
        meta["unread"] = unread
        write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, path=out, error="rows not read: " + "; ".join(unread))
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; not read: {unread}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records from {meta['poll']['rows']} sites -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
