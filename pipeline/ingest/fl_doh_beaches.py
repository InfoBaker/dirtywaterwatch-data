"""Florida Department of Health Healthy Beaches: per-sample beach advisories -> data/build/events/fl-doh-beaches.json

Source
  Florida Department of Health, Florida Healthy Beaches Program (registry row fl-doh-healthy-beaches). Weekly or
  fortnightly enterococcus sampling at about 350 active coastal sampling points.
  - The points: ArcGIS layer https://services1.arcgis.com/CY1LXxl9zlJeBuRZ/arcgis/rest/services/
    FloridaBeachSamplingPoints/FeatureServer/0 (County, EPAbeachID, STORET_Sta, SPLocation, Active, SPLat, SPLong,
    Link). Only Active = Yes points are read.
  - The results: each point's Link opens the beach-detail page on floridahealth.gov, which embeds a Caspio data page
    (https://c0cqk120.caspio.com/dp/cb8a100027f4e6ea6cbc4260a71e) that takes the same query string (County,
    SPLocation, SPNo, SPLat, SPLong) and returns the point's samples, newest first, ten to a page: sample period ID,
    location, sample date, the enterococcus result (CFU/100 mL, sometimes blank) and "Advisory: Yes|No". The first
    page is read (about the last five months of samples); older samples stay from earlier runs.
  No licence is stated; credit "Florida Department of Health, Florida Healthy Beaches Program". The pages carry no
  personal data. One request a second (a fresh connection each; a point with no rows is asked once more).

Passes (2026-11-04): a full pass reads every active point once; a new pass starts at most once every 20 hours
  (from the start of the last completed one; --force starts one sooner). A pass is spread over hourly runs: each run
  reads the points this pass has not read yet, in a fixed order, for at most --budget-s seconds (360 by default), and
  the next run continues where it stopped. The pass and the 20-hour stamp are kept in
  data/build/fl-doh-beaches-state.json, inside the pipeline state the workflow saves. When the data page answers
  without a sample row for REFUSED_RUN points in a row (from a GitHub runner it did so for the last 286 of 352 points
  on 2026-11-04, each costing a 3 s wait and a second request: 23 minutes), the last point that had rows (the probe)
  is asked again: the page says "No records found" both for a point without samples and when it refuses, so only the
  probe tells them apart. The probe still has rows: the five are read (no samples) and the run goes on. It has none,
  or there is no probe yet: the run stops to be safe ("no rows for five points in a row"); the five are not counted
  read. Points not read in a run (set aside, or a request that failed twice) are asked again on the next runs, after
  the points not asked yet; a point not read in GIVE_UP_RUNS runs of a pass is left for that pass (it keeps its
  records; meta.pass.points_given_up), so no point holds a pass open. A point not read this run keeps its previous
  records as they were; the feed's meta.pass says how far the pass got (points read in this pass, of how many, why
  this run stopped), also on a failing run.

Records (beach_advisory; a beach record, never a sewage record)
  Per sampling point, in date order: a sample with Advisory Yes opens an advisory (or continues the open one); the next
  sample with Advisory No ends it: advisory_lifted, ended_at = that sample's date (day precision). One still open is
  advisory_active, source_updated_at = the date of its latest Advisory Yes sample (the status build stops colouring it
  14 days after). started_at is the sample date of the first Advisory Yes result (DOH issues the advisory when the
  laboratory result is known, usually one to three days after sampling: raw.start_basis). DOH's own advisory text and
  signs are not on the page: advice_text is null.
  event_id = fl-doh-beaches:<EPA beach id or county-location>:<sample period ID of the opening sample>.
  waterbody_text = the sampling location as DOH names it (a beach or street end); water_slugs stay empty until
  Florida's water records are built. Coordinates: the point's SPLat/SPLong.

Cadence: daily (results are posted within days of each weekly or fortnightly sample).
Run from pipeline/:  python -m ingest.fl_doh_beaches [--force] [--budget-s S] [--limit N] [--file saved.json]
  --limit N reads the first N points only (a test run: the pass and its stamp are left as they are).
  --file reads {"points": [point attributes ...], "pages": {"<County>|<SPLocation>": "<html>"}} instead of fetching.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, write_events,
                    write_json)

SOURCE_ID = "fl-doh-beaches"
POINTS = ("https://services1.arcgis.com/CY1LXxl9zlJeBuRZ/arcgis/rest/services/FloridaBeachSamplingPoints/"
          "FeatureServer/0")
CASPIO = "https://c0cqk120.caspio.com/dp/cb8a100027f4e6ea6cbc4260a71e"
PAGE_URL = ("https://www.floridahealth.gov/community-environmental-public-health/environmental-public-health/"
            "water-quality/beach-water-quality/")
STATE_FILE = BUILD_DIR / "fl-doh-beaches-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Florida Department of Health (Florida Healthy Beaches Program)"
CREDIT = "Florida Department of Health, Florida Healthy Beaches Program"
POINT_FIELDS = ("FID", "County", "EPAbeachID", "STORET_Sta", "SPLocation", "Active", "SPLat", "SPLong", "Link")
MIN_HOURS = 20
BUDGET_S = 360.0           # seconds of result pages a run may spend; the pass continues next run
REFUSED_RUN = 5            # this many points in a row without a sample row: ask the probe whether the page refuses us
GIVE_UP_RUNS = 3           # a point not read in this many runs of a pass is left for that pass (it keeps its records)
END_BASIS = ("the sample date of the next result without an advisory; the Department of Health lifts the advisory when "
             "that result is known, usually one to three days later, and the page gives no lifting date")
START_BASIS = ("the sample date of the first result with an advisory; the Department of Health issues the advisory "
               "when the laboratory result is known, usually one to three days after sampling")

ROW_RE = re.compile(r'<tr[^>]*class="cbResultSetDataRow[^"]*"[^>]*>(.*?)</tr>', re.S)
CELL_RE = re.compile(r'<td[^>]*class="cbResultSetData[^"]*"[^>]*>(.*?)</td>', re.S)


def text(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_page(page: str) -> list[dict]:
    """The sample rows of one Caspio page: [{period, location, date, enterococcus, advisory}]."""
    out = []
    for row in ROW_RE.findall(page or ""):
        cells = CELL_RE.findall(row)
        flat = " ".join(text(c) for c in cells)
        m_id = re.search(r"\bID:\s*(\d+)", flat)
        m_date = re.search(r"\bDate:\s*(\d{1,2})/(\d{1,2})/(\d{4})", flat)
        m_adv = re.search(r"\bAdvisory:\s*(Yes|No)\b", flat, re.I)
        m_loc = re.search(r"\bLocation:\s*(.*?)\s+Date:", flat)
        m_ent = re.search(r"Enterococcus Code \(Calc\):.*?if\s*\(\s*'([^']*)'", " ".join(cells), re.S)
        if not (m_id and m_date):
            continue
        mo, d, y = (int(x) for x in m_date.groups())
        out.append({"period": m_id.group(1), "location": m_loc.group(1).strip() if m_loc else None,
                    "date": f"{y:04d}-{mo:02d}-{d:02d}",
                    "enterococcus": m_ent.group(1).strip() if m_ent and m_ent.group(1).strip() else None,
                    "advisory": m_adv.group(1).capitalize() if m_adv else None})
    return out


def point_key(p: dict) -> str:
    return f"{p.get('County')}|{p.get('SPLocation')}"


def point_id(p: dict) -> str:
    if p.get("EPAbeachID"):
        base = str(p["EPAbeachID"]).strip()
        return f"{base}-{re.sub(r'[^a-z0-9]+', '-', str(p.get('SPLocation') or '').lower()).strip('-')}"
    return re.sub(r"[^a-z0-9]+", "-", f"{p.get('County')} {p.get('SPLocation')}".lower()).strip("-")


def day(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return datetime(y, m, dd, tzinfo=TZ).isoformat()


def episodes(p: dict, samples: list[dict], fetched_at: str) -> list[dict]:
    """samples: older ones first, the page's rows last: a sample read again replaces the copy kept from an earlier run
    (a result posted late, or an advisory flag corrected)."""
    samples = sorted({s["period"]: s for s in samples}.values(), key=lambda s: (s["date"], int(s["period"])))
    out, ep = [], None
    for s in samples:
        if s.get("advisory") == "Yes":
            if ep is None:
                ep = {"open": s, "samples": [], "last": s}
            ep["samples"].append(s)
            ep["last"] = s
        elif s.get("advisory") == "No" and ep is not None:
            ep["samples"].append(s)
            out.append(make(p, ep, s, fetched_at))
            ep = None
    if ep is not None:
        out.append(make(p, ep, None, fetched_at))
    return out


def make(p: dict, ep: dict, lift: dict | None, fetched_at: str) -> dict:
    o = ep["open"]
    lat, lon = p.get("SPLat"), p.get("SPLong")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        lat = lon = None
    raw = {"county": p.get("County"), "epa_beach_id": p.get("EPAbeachID"), "storet_station": p.get("STORET_Sta"),
           "location": p.get("SPLocation"), "samples": ep["samples"], "start_basis": START_BASIS,
           "detail_page": p.get("Link")}
    status = "advisory_lifted" if lift else "advisory_active"
    if lift:
        raw["end_basis"] = END_BASIS
    return event(
        source_id=SOURCE_ID, source_record_id=f"{point_id(p)}:{o['period']}", fetched_at=fetched_at,
        source_url=p.get("Link") or PAGE_URL, event_type="beach_advisory", status=status,
        waterbody_text=p.get("SPLocation"), water_slugs=[], water_match="none", outfall_name=p.get("SPLocation"),
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=10 if lat is not None else None,
        started_at=day(o["date"]), ended_at=day(lift["date"]) if lift else None, time_precision="day",
        reported_at=None, published_at=None, source_updated_at=day(ep["last"]["date"]),
        material="enterococcus bacteria above the state's beach action value", authority=AUTHORITY,
        advice_text=None, raw=raw,
    )


def caspio_params(p: dict) -> dict:
    q = dict(parse_qsl(urlsplit(p.get("Link") or "").query, keep_blank_values=True))
    if not q:
        q = {"County": p.get("County"), "SPLocation": p.get("SPLocation"), "SPNo": "", "SPLat": p.get("SPLat"),
             "SPLong": p.get("SPLong")}
    return q


def fetch_points(limit: int | None = None) -> list[dict]:
    """The active sampling points, in a fixed order (County|SPLocation), so a pass spread over runs resumes."""
    sess = requests.Session()
    sess.headers.update(HEADERS)
    r = sess.get(f"{POINTS}/query", params={"where": "Active='Yes'", "outFields": ",".join(POINT_FIELDS),
                                            "returnGeometry": "false", "f": "json"}, timeout=(15, 60))
    r.raise_for_status()
    pts = sorted((f["attributes"] for f in r.json().get("features") or []), key=point_key)
    return pts[:limit] if limit else pts


def ask(p: dict, read_s: float = 60.0) -> tuple[str | None, list[dict], str | None]:
    """(page, rows, error) for one point: a fresh request (no session cookie); a page without rows, or a failed
    request, is asked once more after 3 s. read_s: the read timeout (cut to what is left of the run's budget)."""
    page, rows, error = None, [], None
    for attempt in range(2):
        try:
            pr = requests.get(CASPIO, params=caspio_params(p), headers=BROWSER_HEADERS, timeout=(15, read_s))
            pr.raise_for_status()
            page, error = pr.text, None
            rows = parse_page(pr.text)
            if rows or attempt:
                break
        except Exception as e:  # noqa: BLE001
            error = type(e).__name__
            if attempt:
                break
        time.sleep(3)
    return page, rows, error


def fetch_pages(points: list[dict], budget_s: float | None = None,
                probe: dict | None = None) -> tuple[dict, list[str], dict]:
    """(pages, errors, info) for the points in order, until the time budget is used or the data page refuses us.
    probe: a point that had rows earlier in the pass (the last one becomes the probe as the run goes on).
    info: {"asked": points asked, "stopped": why the run stopped asking (None when every point was asked),
    "set_aside": the points of a refusal run (asked, not counted read), "failed": the points whose request failed
    twice, "probe": the key of the last point with rows, "probe_ok": a probe answered with rows, "seconds"}."""
    started = time.monotonic()
    pages, errors, failed, asked, empty_run, stopped, probe_ok = {}, [], [], 0, [], None, False

    def read_s() -> float:
        if budget_s is None:
            return 60.0
        return max(10.0, min(60.0, budget_s - (time.monotonic() - started)))

    for p in points:
        if budget_s is not None and time.monotonic() - started >= budget_s:
            stopped = f"time budget of {budget_s:g} s used"
            break
        asked += 1
        # a fresh request each time (no session cookie) one second apart: with one session, half-second spacing,
        # the data page answered "No records found" for every point after about a hundred requests (2026-11-04)
        page, rows, error = ask(p, read_s())
        if page is not None:
            pages[point_key(p)] = page
        else:
            errors.append(f"{point_key(p)}: {error}")
            failed.append(point_key(p))
        if rows:
            probe = p
        empty_run = [] if rows else empty_run + [point_key(p)]
        if len(empty_run) >= REFUSED_RUN:
            answering = False
            if probe is not None:
                time.sleep(1.0)
                _, probe_rows, _ = ask(probe, read_s())
                answering = bool(probe_rows)
                probe_ok = probe_ok or answering
            if answering:
                # the page answers the probe with its rows: these points have no samples (they are read)
                empty_run = []
            else:
                stopped = (f"no sample rows for {REFUSED_RUN} points in a row and "
                           + ("none for the last point that had rows either" if probe is not None
                              else "no point with rows yet to ask again")
                           + ": stopped to be safe (the page may be refusing requests); those points are asked again "
                             "on the next run")
                break
        time.sleep(1.0)
    set_aside = empty_run if stopped and len(empty_run) >= REFUSED_RUN else []
    for k in set_aside:            # not read: they keep their previous records and are asked again next run
        pages.pop(k, None)
    return pages, errors, {"asked": asked, "stopped": stopped, "set_aside": set_aside,
                           "failed": [k for k in failed if k not in set_aside],
                           "probe": point_key(probe) if probe is not None else None, "probe_ok": probe_ok,
                           "seconds": round(time.monotonic() - started, 1)}


def fetch(limit: int | None = None, budget_s: float | None = None) -> tuple[list[dict], dict, list[str]]:
    pts = fetch_points(limit)
    pages, errors, _ = fetch_pages(pts, budget_s)
    return pts, pages, errors


def build(points: list[dict], pages: dict, prev_records: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    records, seen, samples_n, read, empty = [], set(), 0, 0, 0
    read_points = set()
    for p in points:
        page = pages.get(point_key(p))
        if page is None:
            continue
        rows = parse_page(page)
        read += 1
        if not rows:
            empty += 1
        samples_n += len(rows)
        # samples kept from earlier runs for this point (older than the first page); the fresh rows win
        old = [s for r in prev_records if r.get("raw", {}).get("county") == p.get("County")
               and r.get("raw", {}).get("location") == p.get("SPLocation") for s in r["raw"].get("samples") or []]
        read_points.add((p.get("County"), p.get("SPLocation")))
        for rec in episodes(p, old + rows, fetched_at):
            seen.add(rec["event_id"])
            records.append(rec)
    kept = 0
    for r in prev_records:
        # a point read this run was rebuilt from all its samples: an earlier record it no longer yields (an advisory
        # flag corrected to No) is dropped, not kept
        if (r.get("raw", {}).get("county"), r.get("raw", {}).get("location")) in read_points:
            continue
        if r["event_id"] not in seen:
            records.append(r)
            kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return records, {"points": len(points), "points_read": read, "points_without_samples": empty,
                     "samples_read": samples_n, "kept_from_earlier_runs": kept,
                     "by_status": dict(Counter(r["status"] for r in records))}


def pass_summary(cur: dict, points: list[dict], info: dict) -> dict:
    """meta.pass: how far the pass got (points read in it, of how many, left for it, why this run stopped)."""
    keys = {point_key(p) for p in points}
    given = keys & set(cur.get("given_up") or [])
    done = keys & set(cur.get("done") or [])
    return {"started_at": cur.get("started_at"), "points_read_in_pass": len(done - given), "points": len(keys),
            "points_given_up": sorted(given), "runs": cur.get("runs"), "complete": bool(keys) and done == keys,
            "this_run_stopped": info.get("stopped"), "this_run_set_aside": len(info.get("set_aside") or []),
            "this_run_failed": len(info.get("failed") or []), "this_run_seconds": info.get("seconds")}


def close_pass(state: dict, cur: dict, points: list[dict], info: dict) -> dict:
    """meta.pass; a pass with every point read (or left for it) is closed: the 20-hour cadence counts from its start,
    so each point is read about every 20 hours."""
    meta = pass_summary(cur, points, info)
    if meta["complete"]:
        state["full_pass_at"] = cur["started_at"]
        state.pop("pass", None)
    meta["last_full_pass_at"] = state.get("full_pass_at")
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file")
    ap.add_argument("--force", action="store_true", help="start a new pass even within 20 hours of the last one")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--budget-s", type=float, default=BUDGET_S,
                    help=f"seconds this run may spend on result pages (default {BUDGET_S:g}); the pass continues on "
                         "the next run")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    live_pass = not args.file and not args.limit
    cur = state.get("pass") if live_pass else None
    if live_pass and cur is None and not args.force and state.get("full_pass_at"):
        last = datetime.fromisoformat(state["full_pass_at"].replace("Z", "+00:00"))
        if datetime.now(UTC) - last < timedelta(hours=MIN_HOURS):
            print(f"{SOURCE_ID}: last full pass started {state['full_pass_at']}; next after {MIN_HOURS} h (use --force)")
            return 0
    if live_pass and cur is None:
        cur = {"started_at": fetched_at, "done": [], "runs": 0}
    info = {"stopped": None, "set_aside": [], "failed": [], "seconds": None, "probe_ok": False}
    points = []
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            points, pages, errors = d["points"], d["pages"], []
        else:
            points = fetch_points(args.limit)
            if not points:              # an empty answer from the points layer is an outage, not a pass
                raise RuntimeError("the sampling points layer listed no active point")
            done = set(cur["done"]) if cur else set()
            retry = dict(cur.get("retry") or {}) if cur else {}
            # the points not asked yet first, then those not read on an earlier run of this pass (fewest tries first):
            # a point that does not answer never stands in front of the rest
            todo = sorted((p for p in points if point_key(p) not in done), key=lambda p: retry.get(point_key(p), 0))
            by_key = {point_key(p): p for p in points}
            probe = by_key.get(cur.get("probe")) if cur else None
            pages, errors, info = fetch_pages(todo, args.budget_s, probe=probe)
            if live_pass:
                missed = set(info["set_aside"]) | set(info["failed"])
                for k in missed:
                    retry[k] = retry.get(k, 0) + 1
                given = {k for k in missed if retry[k] >= GIVE_UP_RUNS}
                cur["done"] = sorted(done | set(pages) | given)
                cur["given_up"] = sorted(set(cur.get("given_up") or []) | given)
                cur["retry"] = {k: n for k, n in sorted(retry.items()) if k not in cur["done"]}
                cur["probe"] = info.get("probe") or cur.get("probe")
                cur["runs"] = int(cur.get("runs") or 0) + 1
                state["pass"] = cur
            if todo and not pages:
                raise RuntimeError(f"no result page could be read ({info['stopped'] or 'every request failed'})")
    except Exception as e:  # noqa: BLE001
        meta = None
        if live_pass and cur is not None:
            state.update({"fetched_at": fetched_at, "pass": cur})
            meta = {"pass": close_pass(state, cur, points, info)}
            write_json(STATE_FILE, state)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=meta)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(points, pages, prev, fetched_at)
    if stats["points_read"] >= 10 and stats["points_without_samples"] == stats["points_read"] and not info["probe_ok"]:
        # every page answered without a sample row: the data page changed or refused us ("No records found"); keep the
        # previous records, report the feed as failing and try again next hour (no full_pass_at)
        err = f"no sample rows on any of {stats['points_read']} result pages (layout changed or requests refused)"
        write_events(SOURCE_ID, [], ok=False, error=err)
        print(f"{SOURCE_ID}: FAILED {err}", file=sys.stderr)
        return 1
    pass_meta = None
    if not args.file:
        state.update({"fetched_at": fetched_at, "page_errors": errors[:50]})
        if live_pass:
            pass_meta = close_pass(state, cur, points, info)
        write_json(STATE_FILE, state)
    meta = {**stats, "page_errors": len(errors), "points_layer": POINTS, "results_page": CASPIO, "credit": CREDIT,
            "registry_ids": ["fl-doh-healthy-beaches"]}
    if pass_meta:
        meta["pass"] = pass_meta
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    how_far = ""
    if pass_meta:
        how_far = (f"; pass from {pass_meta['started_at']}: {pass_meta['points_read_in_pass']}/{pass_meta['points']} "
                   f"points read{' (complete)' if pass_meta['complete'] else ''}")
        if info["stopped"]:
            how_far += f"; stopped: {info['stopped']}"
    print(f"{SOURCE_ID}: {stats['points_read']}/{stats['points']} points read this run, {stats['samples_read']} samples "
          f"-> {len(records)} advisory records {stats['by_status']} ({len(errors)} page errors){how_far} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
