"""Knoxville Utilities Board's sanitary sewer overflow log -> data/build/events/tn-kub-sso-log.json

Source (register row TN:tn-kub-public-notice)
  KUB's public page "SSO Logs", https://www.kub.org/forms/sso-logs (an Ember app; 200 to this build's client). Its
  own text (the page's content record, https://www.kub.org/services/forms/3869, read 2026-11-17): "The chart below shows
  the date and location of overflows, which are added within 24 hours of when they are reported, and the status of
  cleanup efforts. The information is posted for the current month or you can select the month and year you would
  like to view. If a month is not shown, no incidents occurred that month." The page reads its rows from
  https://www.kub.org/api/ams/v1/customer-sso-logs?date[]=<first day>:greaterThanOrEquals&date[]=<last day>:lessThanOrEquals&sort=date
  (JSON; 200 to this build's client and to GitHub's runner, run 43971238548; without a date filter it answers 422
  "A date filter with a minimum is required"). Columns shown: Date/Time, Location, Gallons, Status, Completion. Rows
  from 2005 (2,080 on 2026-11-17, 64 in 2026); no id, no water, no point, no permit.
  Law: none for this page (voluntary). KUB reports each overflow to TDEC within 24 hours (Tenn. Comp. R. & Regs.
  0400-40-05-.07(2)(o)), and TDEC's Events Report (tn-tdec-events-report) carries those reports.

Reading (the named client; nothing kept between runs but the state file)
  - Hourly: one request from the first day of the previous month (Eastern) to the last day of this month, so a row
    added on the first of a month for the last day of the one before is read.
  - --backfill: one request per month from BACKFILL_FROM (2023-01-01, the reach the repository keeps for comparable
    statewide lists, as Texas's TCEQ table), PAUSE_S seconds apart, oldest first.
  - Health: a request that fails, an answer that is not this JSON (no customerSsoLog list), or a row with no date is a
    failed read (ok false, the records kept). An answer with no row (a month with no overflow) is a read with nothing
    new.

Records (one sso record per row)
  - source_record_id "<date>T<HHMM or 'day'>:<street key>": the log's date and time and its street after the
    house-number scrub, squeezed to letters and digits; repeats are "~2", "~3" in the order given.
  - Every row read is kept in data/build/tn-kub-sso-log-state.json (the archive); records are rebuilt from it each run.
    A row the log no longer lists when its month is read again keeps its record with raw._missing_from_source_since.
  - Times: the API gives "date" as local midnight in UTC ("2026-03-10T04:00:00.000+00:00": March 10 in Knoxville) and
    "time" as a time of day on 1970-01-01 in UTC; the page shows each in the reader's zone (dayjs "L" and "LT"). Both are
    read as the page shows them in Knoxville (America/New_York): the date's local day, and the time's local hour and
    minute ("1970-01-01T16:49Z" is 11:49 AM). started_at is that minute (time_precision minute); a row with no time is
    the day (time_precision day, no time invented). The page calls it "the date and location of overflows"; it does
    not say whether the time is the start or the report, and raw.time_note says so. ended_at is null and status
    unknown: "Status" and "Completion" are the status of KUB's cleanup (the page's words), kept as
    raw.cleanup_status and raw.cleanup_completed_on, never as the end of the overflow. reported_at and published_at
    stay null (the page says rows are added within 24 hours of the report; raw._first_seen_at is our clock).
  - Volume: "Gallons" as written: a whole number is volume_gal with volume_text "<n> gallons" (estimate_flag unknown:
    the page does not say how it is measured); "Unknown" or nothing is no volume (raw.volume_as_written keeps it).
  - Place: the log names no water and no point. Each record is listed with its street and KUB's service area (Knox
    County, Tennessee) and placed on no water: raw._placement named_water_only, so it is never geolocated from the
    street and never given a plant's point. The log has no field saying whether the sewage reached a water or a storm
    drain; none is inferred.
  - Operator: discharger_id tn-kub (Knoxville Utilities Board, the federal registry's operator); npdes_permit null (the
    log names no plant), raw.operator_permits lists KUB's permits.
  - One event, one record: KUB's overflows also go to TDEC's Events Report (tn-tdec-events-report, read before this
    module; its host has refused automated reading since 2026-11-07, so it holds no new rows). A KUB record is
    duplicate_of the TDEC record of a KUB permit that began the same local day at the same street (link_tdec), so
    it is counted once; raw._duplicate_basis says so.
  - Privacy: the location is a street address, often a home: the house number is removed (common.strip_house_numbers
    and the Alabama reader's leftover-number rule, ingest/al_jefferson_county_soa.street_only); the log carries no
    name, phone or e-mail. The page's contact line is not kept.
Failures: exit 1 for a failed read; --backfill exits 0 when at least one month was read and names the months not read
  in meta.months_not_read (health false), 1 when none was.
Run from pipeline/: python -m ingest.tn_kub_sso_log [--backfill [--from 2023-01-01]] [--file saved.json --out events.json]
Cadence: hourly with the refresh (Tennessee is live).
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest.al_jefferson_county_soa import street_key, street_only

SOURCE_ID = "tn-kub-sso-log"
PAGE = "https://www.kub.org/forms/sso-logs"
API = "https://www.kub.org/api/ams/v1/customer-sso-logs"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
STATE_PATH = BUILD_DIR / "tn-kub-sso-log-state.json"
TDEC_EVENTS = EVENTS_DIR / "tn-tdec-events-report.json"
DISCHARGER_ID = "tn-kub"
DISCHARGER = "Knoxville Utilities Board"
PERMITS = ["TN0021822", "TN0023574", "TN0023582", "TN0061743"]     # data/dischargers.json tn-kub npdes_permits
AUTHORITY = "Knoxville Utilities Board, SSO Logs"
BACKFILL_FROM = "2023-01-01"
PAUSE_S = 2
GALLONS = re.compile(r"\d+")


class ReadError(ValueError):
    """An answer that is not the log this reader knows: a failed read, never "no overflows"."""


def api_url(first: date, last: date) -> str:
    return (f"{API}?date[]={first.isoformat()}:greaterThanOrEquals&date[]={last.isoformat()}:lessThanOrEquals"
            "&sort=date")


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def prev_month(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def months(since: date, today: date) -> list[tuple[date, date]]:
    out, d = [], date(since.year, since.month, 1)
    while d <= today:
        out.append((d, month_end(d)))
        d = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return out


def _instant(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t


def local_day(v) -> date | None:
    t = _instant(v)
    return t.astimezone(TZ).date() if t else None


def local_clock(v) -> tuple[int, int] | None:
    """The hour and minute the page shows for a "time" value in Knoxville (module docstring)."""
    t = _instant(v) if v else None
    if t is None:
        return None
    t = t.astimezone(TZ)
    return t.hour, t.minute


def parse(doc) -> list[dict]:
    """The rows of one answer; ReadError when it is not the log."""
    if not isinstance(doc, dict) or not isinstance(doc.get("customerSsoLog"), list):
        raise ReadError("the answer has no customerSsoLog list")
    rows = []
    for r in doc["customerSsoLog"]:
        if not isinstance(r, dict) or local_day(r.get("date")) is None:
            raise ReadError(f"a row with no readable date: {str(r)[:20]!r}")
        rows.append({k: r.get(k) for k in ("date", "time", "location", "volume", "status", "completionDate")})
    return rows


# ---------------------------------------------------------------- state and records

def row_key(r: dict) -> str:
    d = local_day(r["date"])
    c = local_clock(r.get("time"))
    hm = f"{c[0]:02d}{c[1]:02d}" if c else "day"
    return f"{d.isoformat()}T{hm}:{street_key(street_only(r.get('location')))}"


def keyed(rows: list[dict]) -> list[tuple[str, dict]]:
    out, seen = [], Counter()
    for r in rows:
        base = row_key(r)
        seen[base] += 1
        out.append((base if seen[base] == 1 else f"{base}~{seen[base]}", r))
    return out


def row_hash(r: dict) -> str:
    return hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()[:16]


def take(state: dict, first: date, last: date, rows: list[dict], now: str) -> Counter:
    held = state.setdefault("rows", {})
    got = dict(keyed(rows))
    counts = Counter()
    for rid, r in got.items():
        prev = held.get(rid)
        h = row_hash(r)
        if prev is None:
            held[rid] = {"row": r, "hash": h, "first_seen_at": now, "last_seen_at": now}
            counts["new"] += 1
            continue
        if prev.get("hash") != h:
            prev.update(row=r, hash=h, revised_at=now)
            counts["revised"] += 1
        else:
            counts["same"] += 1
        prev["last_seen_at"] = now
        prev.pop("missing_since", None)
    for rid, h in held.items():
        if first.isoformat() <= rid[:10] <= last.isoformat() and rid not in got and not h.get("missing_since"):
            h["missing_since"] = now
            counts["missing"] += 1
    return counts


def to_record(rid: str, h: dict) -> dict:
    r = h["row"]
    d = local_day(r["date"])
    c = local_clock(r.get("time"))
    if c:
        st, prec = datetime(d.year, d.month, d.day, c[0], c[1], tzinfo=TZ), "minute"
    else:
        st, prec = datetime(d.year, d.month, d.day, tzinfo=TZ), "day"
    vol = " ".join(str(r.get("volume") or "").split())
    gal = int(vol) if GALLONS.fullmatch(vol) else None
    done = local_day(r.get("completionDate"))
    raw = {"state": "TN", "county": "Knox", "time_zone": TZ_NAME, "location": street_only(r.get("location")),
           "place_note": "KUB's service area, Knoxville and Knox County, Tennessee; the log gives a street only",
           "volume_as_written": vol or None, "cleanup_status": (r.get("status") or "").strip() or None,
           "cleanup_completed_on": done.isoformat() if done else None,
           "cleanup_note": ("the log's Status and Completion are, in the page's words, 'the status of cleanup efforts': "
                            "not the end of the overflow"),
           "time_note": ("the log's Date/Time as the page shows it in Knoxville (Eastern time); the page calls it the "
                         "date of the overflow and does not say whether the time is its start or its report"
                         if c else "the log gives a date and no time: the record is dated to the day"),
           "operator_permits": PERMITS, "_placement": "named_water_only",
           "_first_seen_at": h.get("first_seen_at"), "_last_seen_in_source": h.get("last_seen_at")}
    if h.get("missing_since"):
        raw["_missing_from_source_since"] = h["missing_since"]
    return event(
        source_id=SOURCE_ID, source_record_id=rid, event_type="sso", status="unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=None,
        outfall_name=raw["location"], waterbody_text=None,
        started_at=st.isoformat(), ended_at=None, time_precision=prec,
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=h.get("last_seen_at") or now_iso(),
        material="untreated sewage", volume_gal=gal, volume_text=f"{gal:,} gallons" if gal is not None else None,
        estimate_flag="unknown", authority=AUTHORITY, advice_text=None,
        source_url=api_url(date(d.year, d.month, 1), month_end(d)),
        raw={**raw, "page": PAGE})


def _tdec_street(rec: dict) -> str | None:
    name = rec.get("outfall_name")
    if not name or not (rec.get("raw") or {}).get("_outfall_name_basis"):
        return None
    return street_key(name.split(",")[0])


def link_tdec(records: list[dict], tdec: list[dict]) -> Counter:
    """Mark each KUB record duplicate_of TDEC's record of the same overflow (module docstring)."""
    idx: dict[tuple, list[dict]] = {}
    for t in tdec:
        if t.get("npdes_permit") not in PERMITS and t.get("discharger_id") != DISCHARGER_ID:
            continue
        if t.get("duplicate_of"):
            continue
        d, s = local_day(t.get("started_at")), _tdec_street(t)
        if d and s:
            idx.setdefault((d, s), []).append(t)
    used, counts = set(), Counter()
    for r in records:
        key = (local_day(r["started_at"]), street_key(r["raw"].get("location")))
        cand = [t for t in idx.get(key, []) if t["event_id"] not in used]
        if not cand:
            continue
        t = cand[0]
        used.add(t["event_id"])
        r["duplicate_of"] = t["event_id"]
        r["raw"]["_duplicate_basis"] = (f"TDEC's Events Report record of {DISCHARGER} (permit {t.get('npdes_permit')}) "
                                        "began the same day at the same street")
        counts["linked"] += 1
    return counts


def build(state: dict, tdec: list[dict] | None = None) -> tuple[list[dict], Counter]:
    recs = [to_record(rid, h) for rid, h in (state.get("rows") or {}).items()]
    links = link_tdec(recs, tdec if tdec is not None else (read_json(TDEC_EVENTS, {}) or {}).get("records") or [])
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, links


# ---------------------------------------------------------------- fetching

def _get(url: str):
    return requests.get(url, headers=HEADERS, timeout=(20, 90))


def run(now: str, state_path: Path = STATE_PATH, out: Path | None = None, get=_get, backfill: bool = False,
        since: str = BACKFILL_FROM, today: date | None = None, sleep=time.sleep, tdec: list[dict] | None = None,
        save: bool = True) -> int:
    today = today or datetime.now(TZ).date()
    spans = months(date.fromisoformat(since), today) if backfill else [(prev_month(today), month_end(today))]
    state = read_json(state_path, {}) or {}
    counts, not_read, read_any = Counter(), {}, False
    for i, (first, last) in enumerate(spans):
        if i:
            sleep(PAUSE_S)
        try:
            resp = get(api_url(first, last))
            resp.raise_for_status()
            rows = parse(resp.json())
        except (requests.RequestException, ValueError) as e:
            not_read[f"{first:%Y-%m}" if backfill else f"{first:%Y-%m}..{last:%Y-%m}"] = f"{type(e).__name__}: {e}"[:200]
            continue
        read_any = True
        counts.update(take(state, first, last, rows, now))
        if save and rows:
            save_raw(SOURCE_ID, resp.content, "json")
    state["last_read"] = {"at": now, "spans": [f"{a}..{b}" for a, b in spans], **counts}
    if read_any:
        write_json(state_path, state)
    recs, links = build(state, tdec)
    meta = {"registry_ids": [SOURCE_ID], "url": PAGE, "data_url": API, "credit": AUTHORITY, "time_zone": TZ_NAME,
            "reads": [f"{a}..{b}" for a, b in spans], "tdec_links": dict(links), "covers_operator": DISCHARGER_ID,
            "carried_from": BACKFILL_FROM}
    if not_read:
        meta["months_not_read"] = not_read
        err = "log not read: " + "; ".join(f"{m}: {w}" for m, w in not_read.items())
        if not read_any:
            write_events(SOURCE_ID, [], ok=False, error=err, meta=meta, path=out)
            print(f"{SOURCE_ID}: FAILED {err}", file=sys.stderr)
            return 1
        write_events(SOURCE_ID, recs, ok=False, partial=True, error=err, meta=meta, path=out)
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; {err}", file=sys.stderr)
        return 0 if backfill else 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records ({dict(counts)}; TDEC links {dict(links)}) -> {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="read each month from --from")
    ap.add_argument("--from", dest="since", default=BACKFILL_FROM)
    ap.add_argument("--file", help="a saved answer of the data address, read in place of the live one (needs --out)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.file and not a.out:
        ap.error("--file needs --out")
    out = Path(a.out) if a.out else None
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    if a.file:
        rows = [r for r in parse(json.loads(Path(a.file).read_text())) if str(local_day(r["date"])) >= a.since]
        state = read_json(state_path, {}) or {}
        days = sorted(str(local_day(r["date"])) for r in rows)
        if days:
            take(state, date.fromisoformat(days[0]), date.fromisoformat(days[-1]), rows, now_iso())
        write_json(state_path, state)
        recs, links = build(state)
        write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "url": PAGE, "tdec_links": dict(links)},
                     path=out)
        print(f"{SOURCE_ID}: {len(recs)} records from {a.file}")
        return 0
    return run(now_iso(), state_path, out, backfill=a.backfill, since=a.since)


if __name__ == "__main__":
    sys.exit(main())
