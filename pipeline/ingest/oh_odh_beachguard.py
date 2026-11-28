"""Ohio Department of Health BeachGuard, current and past advisories -> data/build/events/oh-odh-beachguard.json.

Source (registry oh-odh-beachguard; research/oh/report.md section 2.5)
  The JSON behind BeachGuard's public pages: https://publicapps.odh.ohio.gov/beachguardpublic/api/advisorieslist with
  queryParams {"filter":[{"isCurrentAdvisory":true}]}: one row per advisory in effect at a public or private bathing
  beach, entered by the issuing organisation (a local health district, the Ohio Department of Natural Resources).
  Fields read (SAFE_FIELDS): id (the advisory's own id), beachId, beachName, beachAccessTypeId, parkName,
  waterBodyName, waterBodyTypeId, countyName, issuingOrganizationName, typeId, typeText, typeSeverityLevel,
  reasonTypeText, pollutionSourceTypeText, startDate ("05/20/2026 11:10 AM", Ohio's wall clock), reopenDate
  ("Ongoing" or a date), comment (free text, scrubbed: below), latitudeCenter, longitudeCenter. Excluded: metadata and
  thisObject (the API's own scaffolding), the lookup ids (countyId, issuingOrganizationId, reasonTypeId,
  pollutionSourceTypeId) and daysUnderAdvisory (derived from the start); isCurrentAdvisory is kept (true on the
  current list; on the full list it tells a past advisory from one in effect).
  The full list (every advisory since 2008: 8,657 on 2026-11-21, 468 begun in 2026 at 110 beaches) is refused whole
  ("A JSON string exceeds the maximum allowed number of characters", 2026-11-08) but pages: queryParams
  {"top":1500,"skip":N,"orderBy":["id desc"]}, about 3.8 MB a page, hasResultsRemaining false on the last
  (fetch_history). It is read on --backfill and again when the last read is HISTORY_EVERY_DAYS old. Until
  2026-11-21 only the current list was read (5 advisories on 2026-11-08), so the feed held none of the season's
  advisories that had already ended.
  Types (typeId): CONTAM_ADV "Bacteria Contamination Advisory" -> beach_advisory (the beach-advisory category);
  HAB_WATCH_ADV, HAB_WARNING_ADV ("Recreational Public Health Advisory"), HAB_CAUTION and any other HAB_ type ->
  hab_advisory (the algal-bloom category, plum); a type naming a closure -> beach_closure; any other type ->
  beach_advisory with raw.type_unmapped.

Records (the authority's own advisory, red while it stands: plan section 2)
  - One record per advisory id: started_at the start date (America/New_York, minute; raw.time_zone), status
    advisory_active while the list shows it; source_updated_at null (the list gives no update time); fetched_at and
    raw._last_seen_in_source the last poll that listed it.
  - When the list stops showing it, advisory_lifted with ended_at the first poll that did not list it
    (raw.ended_at_precision poll, raw.lift_observed_between). A reopenDate the list gave is kept in raw (the issuer's
    expected reopening), never used as the end. A list that empties at once lifts nothing until the next poll is
    empty too (dated at the first empty poll); a failed fetch lifts nothing.
  - A past advisory (the full list, isCurrentAdvisory false) is a record too: advisory_lifted, started_at its start
    date, ended_at its reopenDate (the issuing organisation's reopening; the default of the Ohio decisions, item 7:
    the issuer's end for past advisories), raw.ended_at_precision minute, or day where the list gives a date only
    (5,157 starts before 2022 are dates only: time_precision day). One the polls saw in the current list keeps the
    poll's lift unless the reopening falls between the last poll that listed it and the poll that lifted it (then the
    reopening, the issuer's time, is the end; the poll window stays in raw). A past advisory with no reopening date is
    kept with status unknown and says so. The full list never opens, re-confirms or lifts an advisory in effect: the
    current list decides those.
  - Place: the beach's centre point (coord_source source), waterbody_text the water body's name (a bare "Lake" or
    "Pond" is none); raw.county; authority the issuing organisation "(Ohio BeachGuard)". A point is a marker; the
    status build draws no whole-water colour from it beyond its rules.
  Privacy: only SAFE_FIELDS are kept and the raw save holds only them; the comment runs through Illinois's
  BeachGuard scrub (il_idph_beachguard.scrub_comment: a name after "call" or "contact", then
  mi_egle_mienviro.free_text) before it is stored, with measurements ("252 cfu/100mL") shielded from the address
  rule; common.event runs strip_personal.

State: data/build/oh-odh-beachguard-state.json (every advisory seen, current or past; history.read_at): the archive,
do not delete.
Run from pipeline/: python -m ingest.oh_odh_beachguard [--backfill] [--file saved.json [--history-file page.json ...]
                    --out events.json]
--backfill reads the full list now (exit 1 only when that read fails; the current list is still written).
Cadence: hourly with the refresh (the current list); the full list weekly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from common import error_detail, error_text

SOURCE_ID = "oh-odh-beachguard"
API = "https://publicapps.odh.ohio.gov/beachguardpublic/api/advisorieslist"
QUERY = '{"filter":[{"isCurrentAdvisory":true}]}'
PAGE_URL = "https://publicapps.odh.ohio.gov/beachguardpublic/"
SAFE_FIELDS = ["id", "beachId", "beachName", "beachAccessTypeId", "parkName", "waterBodyName", "waterBodyTypeId",
               "countyName", "issuingOrganizationName", "typeId", "typeText", "typeSeverityLevel", "reasonTypeText",
               "pollutionSourceTypeText", "startDate", "reopenDate", "comment", "latitudeCenter", "longitudeCenter",
               "isCurrentAdvisory"]
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
STATE_PATH = BUILD_DIR / "oh-odh-beachguard-state.json"
EMPTY_POLLS_TO_LIFT = 2
CREDIT = "Ohio Department of Health, BeachGuard"
GENERIC_WATER = re.compile(r"^(lake|pond|beach|river|reservoir|quarry)$", re.I)
PAGE_SIZE = 1500                  # rows per page of the full list (about 3.8 MB)
MAX_PAGES = 40                    # 60,000 rows: a list that does not end by then is a fault, not history
HISTORY_EVERY_DAYS = 7
REOPEN_BASIS = ("BeachGuard's reopening date for a past advisory (the issuing organisation's, from the full list of "
                "advisories)")


def event_type_of(type_id: str | None, type_text: str | None) -> tuple[str, bool]:
    """(event_type, mapped) for a BeachGuard advisory type."""
    t = str(type_id or "").strip().upper()
    if t.startswith("HAB"):
        return "hab_advisory", True
    if "CLOS" in t or re.search(r"(?i)clos", str(type_text or "")):
        return "beach_closure", True
    if t == "CONTAM_ADV":
        return "beach_advisory", True
    return "beach_advisory", False


def when(text) -> tuple[str | None, str | None]:
    """(ISO time, precision) for BeachGuard's "05/20/2026 11:10 AM" (minute) or "09/04/2015" (day, local midnight);
    (None, None) for "Ongoing", blank or anything else."""
    t = str(text or "").strip()
    for fmt, prec in (("%m/%d/%Y %I:%M %p", "minute"), ("%m/%d/%Y", "day")):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=TZ).isoformat(), prec
        except ValueError:
            continue
    return None, None


def start_time(text) -> str | None:
    return when(text)[0]


def _t(iso: str) -> datetime:
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


# a measurement ("252 cfu/100mL", "8.2 ug/L") is no house number: shielded from the address scrub, then restored
MEASURE = re.compile(r"(?i)\b\d+(?:\.\d+)?(?=\s*(?:cfu|mpn|colonies|ug/?l|\u00b5g/?l|ppb|mg/?l|cells|%))")


def clean_comment(v) -> str | None:
    """Keep published comments; a blank field remains absent."""
    return v or None


def rows_of(doc) -> list[dict]:
    rows = doc.get("queryResults") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise ValueError("no queryResults list in the answer")
    out = []
    for r in rows:
        a = {k: (r or {}).get(k) for k in SAFE_FIELDS}
        a["comment"] = clean_comment(a.get("comment"))
        for k in ("parkName", "beachName", "waterBodyName", "countyName", "issuingOrganizationName",
                  "pollutionSourceTypeText", "beachAccessTypeId"):
            if isinstance(a.get(k), str):
                a[k] = " ".join(a[k].split()) or None
        out.append(a)
    return out


def fetch_history(sess, page_size: int = PAGE_SIZE) -> list[dict]:
    """Every advisory on BeachGuard's full list, page by page ("top", "skip", ordered by id), until the answer says
    hasResultsRemaining false or a page comes back empty; each row cut to SAFE_FIELDS and scrubbed (rows_of). A row
    met twice (the list moved while it was read) is kept once. ValueError on an error answer or a list longer than
    MAX_PAGES."""
    out, seen = [], set()
    for n in range(MAX_PAGES):
        q = json.dumps({"top": page_size, "skip": n * page_size, "orderBy": ["id desc"]}, separators=(",", ":"))
        r = sess.get(API, params={"queryParams": q}, timeout=(20, 300))
        r.raise_for_status()
        doc = r.json()
        if isinstance(doc, dict) and (doc.get("responseStatus") or {}).get("errorCode"):
            raise ValueError(f"the API answered an error on page {n + 1}: {doc['responseStatus'].get('errorCode')}")
        page = rows_of(doc)
        if not page and doc.get("hasResultsRemaining"):
            raise ValueError(f"page {n + 1} of the full list was empty but said more rows remain")
        for a in page:
            k = str(a.get("id"))
            if k not in seen:
                seen.add(k)
                out.append(a)
        if not page or not doc.get("hasResultsRemaining"):
            if not out:
                raise ValueError("the full list answered no rows (it held 8,657 on 2026-11-21)")
            return out
    raise ValueError(f"the full list did not end within {MAX_PAGES} pages of {page_size}")


def history_due(state: dict, now: str) -> bool:
    """True when the full list has never been read or was last read HISTORY_EVERY_DAYS or more ago."""
    at = (state.get("history") or {}).get("read_at")
    return not at or (_t(now) - _t(at)).total_seconds() >= HISTORY_EVERY_DAYS * 86400


def apply_history(state: dict, rows: list[dict], now: str) -> dict:
    """Fold the full list into the archive: a past advisory not seen before becomes a record; one the current list
    listed keeps its own row, and the full list's row is kept beside it (history_row: its reopening date), so the full
    list never rewrites an advisory the current list shows (Astra 2026-11-21 P1). An advisory in effect
    (isCurrentAdvisory true) is left to the current list."""
    recs = state.setdefault("records", {})
    counts = {"rows": len(rows), "past": 0, "current": 0, "new": 0}
    for a in rows:
        if a.get("isCurrentAdvisory") is True:
            counts["current"] += 1
            continue
        counts["past"] += 1
        key = str(a.get("id") or f"{a.get('beachId')}-{a.get('typeId')}-{a.get('startDate')}")
        rec = recs.get(key)
        if rec is None:
            recs[key] = {"row": a, "history_seen_at": now}
            counts["new"] += 1
        elif rec.get("last_listed_at"):
            rec.update(history_row=a, history_seen_at=now)
        else:
            rec.update(row=a, history_seen_at=now)
    state["history"] = {"read_at": now, **counts}
    return counts


def fetch(sess) -> list[dict]:
    r = sess.get(API, params={"queryParams": QUERY}, timeout=(20, 300))
    r.raise_for_status()
    doc = r.json()
    if isinstance(doc, dict) and doc.get("responseStatus", {}).get("errorCode"):
        raise ValueError(f"the API answered an error: {doc['responseStatus'].get('errorCode')}")
    return rows_of(doc)


def apply(state: dict, rows: list[dict], now: str) -> dict:
    recs = state.setdefault("records", {})
    open_ = state.setdefault("open", [])
    counts = {"opened": 0, "kept": 0, "lifted": 0}
    if not rows and open_:
        first = state.setdefault("empty_since", now)
        state["empty_polls"] = state.get("empty_polls", 0) + 1
        if state["empty_polls"] < EMPTY_POLLS_TO_LIFT:
            counts["held"] = len(open_)
            return counts
        now = first
    state.pop("empty_since", None)
    state.pop("empty_polls", None)
    listed = []
    for a in rows:
        key = str(a.get("id") or f"{a.get('beachId')}-{a.get('typeId')}-{a.get('startDate')}")
        listed.append(key)
        rec = recs.get(key)
        if rec is None:
            rec = recs[key] = {"first_listed_at": now}
            counts["opened"] += 1
        else:
            counts["kept"] += 1
        rec.update(row=a, last_listed_at=now)
        rec.pop("lifted_at", None)
        rec.pop("lift_between", None)
    for key in open_:
        if key not in listed and key in recs and not recs[key].get("lifted_at"):
            recs[key].update(lifted_at=now, lift_between=[recs[key]["last_listed_at"], now])
            counts["lifted"] += 1
    state["open"] = listed
    return counts


def _end(r: dict, a: dict, raw: dict) -> tuple[str, str | None, str | None]:
    """(status, ended_at, parse_error) of one archived advisory; writes the end's precision and basis into raw."""
    listed, lifted = r.get("last_listed_at"), r.get("lifted_at")
    h = r.get("history_row") if listed else a              # the full list's row for an advisory the polls listed
    past = bool(h) and h.get("isCurrentAdvisory") is False and r.get("history_seen_at")
    if listed and h:
        a = dict(a, reopenDate=h.get("reopenDate"))
    reopen, rprec = when(a.get("reopenDate"))
    start = when(a.get("startDate"))[0]
    if reopen and start and _t(reopen) < _t(start):
        reopen = None
        raw["reopen_note"] = f"BeachGuard's reopening date {a['reopenDate']} is before the start; it is not used"
    if listed is None:                       # known only from the full list: a past advisory
        if reopen:
            raw.update(ended_at_precision=rprec, end_basis=REOPEN_BASIS)
            return "advisory_lifted", reopen, None
        return "unknown", None, "BeachGuard lists it as a past advisory but gives no reopening date"
    if not lifted:
        if a.get("reopenDate") and str(a["reopenDate"]).strip().lower() != "ongoing":
            raw["reopen_note"] = f"BeachGuard listed a reopening date of {a['reopenDate']}; it is not used as the end"
        return "advisory_active", None, None
    raw.update(lift_observed_between=r["lift_between"],
               lift_basis="BeachGuard's list of current advisories stopped listing it")
    if past and reopen and _in_window(reopen, rprec, listed, lifted):
        raw.update(ended_at_precision=rprec, end_basis=REOPEN_BASIS)
        return "advisory_lifted", reopen, None
    raw["ended_at_precision"] = "poll"
    if a.get("reopenDate") and str(a["reopenDate"]).strip().lower() != "ongoing" and "reopen_note" not in raw:
        raw["reopen_note"] = (f"BeachGuard listed a reopening date of {a['reopenDate']}; it is not used as the end "
                              "(it falls outside the polls that last listed it and then lifted it)")
    return "advisory_lifted", lifted, None


def _in_window(reopen: str, prec: str, listed: str, lifted: str) -> bool:
    """True when the reopening falls between the last poll that listed the advisory and the poll that lifted it; a
    reopening given as a date only counts as its whole local day (any part of the day inside the window)."""
    r0 = _t(reopen)
    if prec == "day":
        nxt = (r0.astimezone(UTC) + timedelta(days=1, hours=1)).astimezone(TZ)
        r1 = datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ)
        return r0 <= _t(lifted) and r1 >= _t(listed)
    return _t(listed) <= r0 <= _t(lifted)


def to_record(key: str, r: dict) -> dict:
    a = r["row"]
    et, mapped = event_type_of(a.get("typeId"), a.get("typeText"))
    water = a.get("waterBodyName")
    first = r.get("first_listed_at") or r.get("history_seen_at")
    raw = {"advisory": {k: v for k, v in a.items() if k not in ("latitudeCenter", "longitudeCenter")},
           "county": a.get("countyName"), "time_zone": TZ_NAME, "state": "OH", "_first_seen_at": first,
           "start_basis": "the advisory's start date as BeachGuard lists it"}
    if r.get("last_listed_at"):
        raw["_last_seen_in_source"] = r["last_listed_at"]
    if r.get("history_seen_at"):
        raw["_seen_in_full_list_at"] = r["history_seen_at"]
    if not mapped:
        raw["type_unmapped"] = f"advisory type {a.get('typeId')!r} read as a beach advisory"
    status, ended, problem = _end(r, a, raw)
    start, precision = when(a.get("startDate"))
    if start is None:
        problem = problem or f"unreadable start date {a.get('startDate')!r}"
    reason = "; ".join(x for x in (a.get("reasonTypeText"),
                                   f"source: {a['pollutionSourceTypeText']}" if a.get("pollutionSourceTypeText") else None,
                                   a.get("comment")) if x)
    raw["reason"] = reason or None
    beach = " - ".join(x for x in (a.get("beachName"), a.get("parkName")) if x)
    org = a.get("issuingOrganizationName")
    lat, lon = a.get("latitudeCenter"), a.get("longitudeCenter")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=et, status=status,
        waterbody_text=None if not water or GENERIC_WATER.match(water) else water,
        lat=lat if isinstance(lat, (int, float)) else None, lon=lon if isinstance(lon, (int, float)) else None,
        coord_source="source" if isinstance(lat, (int, float)) else None,
        started_at=start, ended_at=ended, time_precision=precision or "minute",
        reported_at=None, published_at=None, source_updated_at=None,
        fetched_at=r.get("last_listed_at") or r.get("history_seen_at"), parse_error=problem,
        authority=(f"{org} (Ohio BeachGuard)" if org else CREDIT) + (f": {a['typeText']}" if a.get("typeText") else ""),
        outfall_name=beach or None,
        advice_text=a.get("comment") or None,   # the issuer's own words only; the type and reason are in raw
        source_url=PAGE_URL, raw=raw)


def run(state: dict, rows: list[dict], now: str, history: list[dict] | None = None) -> tuple[list[dict], dict]:
    counts = apply(state, rows, now)
    state["last_poll"] = {"at": now, "listed": len(rows), **counts}
    if history is not None:
        apply_history(state, history, now)
    recs = [to_record(k, r) for k, r in state["records"].items()]
    recs.sort(key=lambda x: (x["started_at"] or "", x["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "api": API, "poll": state["last_poll"], "credit": CREDIT,
            "history": state.get("history"),
            "time_note": "Start dates are BeachGuard's (Eastern time). A past advisory ends at the reopening BeachGuard "
                         "gives; one in effect when we polled ends at the first poll that no longer listed it, or at "
                         "the reopening when that falls between the two polls."}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="a saved API answer (needs --out; its state is kept next to that file)")
    ap.add_argument("--history-file", action="append", default=[], help="a saved page of the full list (with --file)")
    ap.add_argument("--out")
    ap.add_argument("--backfill", action="store_true", help="read the full list now (every advisory since 2008)")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out:
            ap.error("--file needs --out (only live polls reach the archive)")
        out = Path(a.out)
        st_path = out.with_suffix(".state.json")
        state = read_json(st_path, {}) or {}
        hist = [x for f in a.history_file for x in rows_of(json.loads(Path(f).read_text()))] if a.history_file else None
        recs, meta = run(state, rows_of(json.loads(Path(a.file).read_text())), now, history=hist)
        write_json(st_path, state)
        write_events(SOURCE_ID, recs, meta=meta, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {out}")
        return 0
    sess = requests.Session()
    sess.headers.update(HEADERS)
    state = read_json(STATE_PATH, {}) or {}
    try:
        rows = fetch(sess)
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"API: {error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(rows), "json")
    hist, hist_error = None, None
    if a.backfill or history_due(state, now):
        try:
            hist = fetch_history(sess)
        except (requests.RequestException, ValueError) as e:
            hist_error = f"the full list (history) was not read: {error_text(e)}"
    recs, meta = run(state, rows, now, history=hist)
    if hist_error:
        meta["history_error"] = hist_error
    write_json(STATE_PATH, state)
    path = write_events(SOURCE_ID, recs, meta=meta)
    h = state.get("history") or {}
    print(f"{SOURCE_ID}: {len(recs)} records, {len(rows)} listed now"
          + (f", full list read: {h.get('rows')} rows, {h.get('past')} past" if hist is not None else "")
          + f" -> {path}" + (f"; {hist_error}" if hist_error else ""))
    if hist_error and a.backfill:
        print(f"{SOURCE_ID}: backfill FAILED: {hist_error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
