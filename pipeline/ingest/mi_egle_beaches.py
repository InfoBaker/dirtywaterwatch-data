"""Michigan EGLE beach closures and contamination advisories (MiEnviro) -> data/build/events/mi-egle-beachguard.json

Source (registry mi-egle-beachguard; docs/analysis/2026-11-21-swimguide.md in the site repository, section 4)
  Michigan Department of Environment, Great Lakes, and Energy (EGLE), Beach Monitoring Program: the map "MiEnviro
  nSITE beach explorer" (https://mienviro.michigan.gov/nsite/beach/map/), where local health departments enter their
  beach closures and contamination advisories. The map's own Export button reads an unauthenticated CSV service,
  GET https://mienviro.michigan.gov/nsite/ss/explorersiteexports?responseContentType=text/csv
  &includeMetadataInResponse=false&loadChildren=true&queryParams=<JSON {"filter":[{"reportId":N, the map box,
  "modeId":"BEACH", "isIncludeUnmappable":true, ...}]}>&filterString= with the map page as Referer (400 without
  it). No key, no cookie; the body is gzip. Only the map's per-beach detail services (beachadvisories, beachresults)
  answer 401; the export does not need them. Reports (ids from /nsite/api/settings/getWslSettings?environment=beach):
  - 2082 "Closures and Contamination Advisories": every advisory since 1994 (3,655 on 2026-11-21, 246 begun in 2026
    at 152 beaches): StartDate, EndDate (dates: "6/12/2026 12:00:00 AM"), AdvisoryType (Closed, Contamination
    Advisory), Reason, PollutionSource, DaysUnderAdvisory, IssuingOrganization, AdvisoryComments, Name, Identifier
    (the beach's id). One request each run (about 63 KB gzip), asking for ADV_KEPT only (responseFields), so
    AdvisoryComments is not sent; an answer with every field is still read and the comments dropped.
  - 2081 "Beach Details": the 2,914 sites with their point, county, waterbody, EPA beach id and access. Read at most
    once a day (SITES_MAX_AGE_H) and whenever an advisory names a beach the saved list lacks; only SITE_FIELDS are
    kept (data/build/mi-egle-beaches-sites.json). A new answer is added to the saved list (a beach it lacks keeps its
    saved point) and one under MIN_SITES or MIN_SHARE of the saved list is not used.
  - 2078 "Sampling Results" (452,680 rows) is not read.
  No licence statement (michigan.gov: "Copyright State of Michigan"). Credit "Michigan EGLE, MiEnviro beach
  monitoring". Law: the BEACH Act (CWA 406) and Part 31 of Michigan's NREPA (Rule 62: E. coli 300 per 100 mL as a
  daily geometric mean, 130 as a 30-day mean); EGLE says local health departments post advisories "within 24 hours".

Privacy (what is kept)
  AdvisoryComments (free text by health department staff) is not requested (responseFields) and, if sent anyway, never
  kept: not in a record, not in raw, not in the saved raw read. Report 2081 refuses a field list by its display
  names, so its private columns arrive and are dropped while parsing, before anything is saved. From report 2081 only SITE_FIELDS are kept: never "Site Information - Private Comments", "Site
  Information - Additional Comments", "Beach Description" or "Site Information - Facilities". Points are rounded to
  three decimals (POINT_DECIMALS): private beaches are among the sites. common.event runs strip_personal.

Records (category beach: beach_closure or beach_advisory; never a sewage discharge record)
  - One per advisory row. Key (source_record_id): "<Identifier>-<start YYYYMMDD>-<closure|advisory>". Rows that are
    identical in every kept field are one advisory (8 such pairs on 2026-11-21); rows that share the key and differ (two
    in 2005 and 2006, with different ends) take "-2", "-3" by the order of (end, reason, source, issuer) when first
    seen, and keep them after: the assignment is saved (state collision_ids), so a corrected end never swaps ids.
  - AdvisoryType Closed -> beach_closure; Contamination Advisory -> beach_advisory; any other type -> beach_advisory
    with raw.type_unmapped.
  - started_at and ended_at are the dates as EGLE gives them (the export carries no time of day: 12:00 AM on every
    row), time_precision "day", in the beach's clock (raw.time_zone): Eastern, or Central in the four Upper
    Peninsula counties on the Wisconsin line (MI_CENTRAL_COUNTIES, 49 CFR 71.5). An end before the start is not used
    (raw.end_not_used).
  - Status: advisory_lifted when the end's local day is over at the read, else advisory_active. An advisory with no
    end (4 on 2026-11-21, begun in August and September) is advisory_active with raw.no_end_in_source true and no
    raw._last_seen_in_source: the export is an archive table with no update time, so an open row confirms only what
    EGLE entered at its start. The status build colours it to CONFIRM_DAYS after the start and then shows it as not
    re-confirmed (never as lifted).
  - The reason: raw.reason (EGLE's Reason: High bacteria levels, Rainfall, Sewage, Chemical or Oil discharge, Other,
    Not Specified) and raw.pollution_source (Unknown, Storm water runoff, Wildlife, Sanitary Sewer Overflow, Combined
    Sewer Overflow ...). data/rules.json beach_reason reads them (decision 40; the entry is BEACH_REASON_ENTRY):
    "Other" and "Not Specified" with no stated source are listed without a colour.
  - Place: the site's point (coord_source source), waterbody_text the site's Waterbody, outfall_name the beach name
    (and park); raw.county, raw.access (Public Owned, Public Access; Private Owned, Private Access; Not a Beach ...),
    raw.great_lake, raw.epa_beach_id (BEACON's beach id, for its copy links). A beach missing from report 2081 is a
    record without a point (meta.no_site).
  - authority "<IssuingOrganization> (Michigan EGLE beach monitoring)"; published_at, reported_at and
    source_updated_at are empty (the export gives no posting or entry time); fetched_at the read; raw._first_seen_at
    the first read that listed the advisory (kept in the state file).

Checks: the header must be the expected one. A row must be as wide as the header, with a numeric Identifier, a start
  date, a type, a name and an end that is empty or a date; a malformed row is left out whole (meta.rows_rejected), and
  a read with more than MAX_REJECTED of them (or 1%) is refused. A read with fewer than MIN_ROWS distinct advisories,
  or fewer than MIN_SHARE of those the last good read held, is refused (the export is cumulative, so it only grows). A
  beach list under MIN_SITES or MIN_SHARE of the saved one never replaces it. A refused or failed read keeps the
  previous records (write_events ok false).
State: data/build/mi-egle-beaches-state.json (first_seen per key, the last good row count) and
  data/build/mi-egle-beaches-sites.json (report 2081's kept fields).
Run from pipeline/: python -m ingest.mi_egle_beaches [--advisories saved.csv --sites saved.csv --out events.json]
Cadence: hourly with the refresh.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, error_detail, event, now_iso, read_json, save_raw, write_events, write_json
import zones

SOURCE_ID = "mi-egle-beachguard"
MAP_PAGE = "https://mienviro.michigan.gov/nsite/beach/map/"
EXPORT = "https://mienviro.michigan.gov/nsite/ss/explorersiteexports"
REPORT_ADVISORIES = 2082
REPORT_SITES = 2081
# the map's box around Michigan; isIncludeUnmappable takes the sites without a point too (a wider box gives the same
# 3,655 advisories, 2026-11-21)
BOX = {"latitudeMin": 41.5, "latitudeMax": 48.5, "longitudeMin": -90.6, "longitudeMax": -82.0}
ADV_COLUMNS = ["StartDate", "EndDate", "AdvisoryType", "Reason", "PollutionSource", "DaysUnderAdvisory",
               "IssuingOrganization", "AdvisoryComments", "Name", "Identifier"]
ADV_KEPT = [c for c in ADV_COLUMNS if c != "AdvisoryComments"]
SITE_FIELDS = {"Beach ID": "beach_id", "Beach Name": "name", "Latitude": "lat", "Longitude": "lon", "County": "county",
               "Waterbody": "waterbody", "EPA Beach ID": "epa_beach_id",
               "Site Information - Accessibility": "access", "Site Information - Great Lake": "great_lake",
               "Park Information - Park Name": "park"}
POINT_DECIMALS = 3
MI_CENTRAL_COUNTIES = frozenset({"GOGEBIC", "IRON", "DICKINSON", "MENOMINEE"})
STATE_PATH = BUILD_DIR / "mi-egle-beaches-state.json"
SITES_PATH = BUILD_DIR / "mi-egle-beaches-sites.json"
SITES_MAX_AGE_H = 24
MIN_ROWS = 1000          # distinct advisories; the export held 3,650 on 2026-11-21 and only grows
MIN_SHARE = 0.9          # a read with fewer advisories than this share of the last good read is refused
MAX_REJECTED = 10        # malformed rows a read may carry (each left out and counted); more refuses the read
MAX_REJECTED_SHARE = 0.01
MIN_SITES = 2000         # report 2081 listed 2,914 sites on 2026-11-21
CREDIT = "Michigan EGLE, MiEnviro beach monitoring"
GENERIC_WATER = re.compile(r"^(lake|pond|beach|river|reservoir|quarry|creek)$", re.I)
TYPES = {"closed": ("beach_closure", "closure"), "contamination advisory": ("beach_advisory", "advisory")}
# Decision 40's entry for this source, as data/rules.json beach_reason.sources should carry it. rules.json has one writer
# (the build coordinator integrates it at merge, .coordinator/work/mi-beaches/shared-files.patch); the tests check the
# file's entry equals this one once it is there.
BEACH_REASON_ENTRY = {
    "kind": "fields",
    "fields": ["reason", "pollution_source", "advisory_type"],
    "read": "EGLE's reason and pollution source for the closure or advisory, as its MiEnviro beach export lists them",
}


class ReadError(Exception):
    """An export answer that is not the report it should be (empty, a changed header, too few rows)."""


def _clean(v) -> str:
    return " ".join(str(v or "").split())


def query_params(report_id: int) -> str:
    flt = {"displayHeight": 900, "displayWidth": 1400, "filterValuesJson": None, "isIncludeUnmappable": True,
           "reportId": report_id, **BOX, "modeId": "BEACH", "searchTerm": ""}
    return json.dumps({"filter": [flt]}, separators=(",", ":"))


def decode(body: bytes) -> str:
    """The CSV text of an answer: gzip when the server sent it without the header requests decodes."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body.decode("utf-8-sig")


def fetch_report(sess, report_id: int, fields: list[str] | None = None) -> str:
    """One export report as CSV text. fields: responseFields, the columns to ask for (report 2082 honours it, so its
    AdvisoryComments never leaves EGLE's server; report 2081 refuses its display names, 400 "is not a field")."""
    params = {"responseContentType": "text/csv", "includeMetadataInResponse": "false", "loadChildren": "true",
              "queryParams": query_params(report_id), "filterString": ""}
    if fields:
        params["responseFields"] = ",".join(fields)
    r = sess.get(EXPORT, params=params, headers={"Accept": "text/csv", "Referer": MAP_PAGE}, timeout=(20, 180))
    r.raise_for_status()
    if not str(r.headers.get("content-type", "")).startswith("text/csv"):
        raise ReadError(f"report {report_id}: not CSV ({r.headers.get('content-type')})")
    return decode(r.content)


def _valid(r: dict, columns: list[str]) -> bool:
    """A row as wide as the header with an identifier, a start date, a type and a name, and an end that is empty or
    a date (Astra review 2026-11-21 P1: a row shifted by an unquoted comma is never kept)."""
    if "__extra__" in r or any(r.get(k) is None for k in columns):
        return False
    return bool(re.fullmatch(r"\d+", _clean(r["Identifier"])) and parse_date(r["StartDate"])
                and (not _clean(r["EndDate"]) or parse_date(r["EndDate"]))
                and _clean(r["AdvisoryType"]) and _clean(r["Name"]))


def read_advisories(text: str) -> tuple[list[dict], int]:
    """(the valid advisory rows with ADV_KEPT only, the number of malformed rows left out). AdvisoryComments is
    dropped here, before anything is saved; a malformed row is dropped whole."""
    rd = csv.DictReader(io.StringIO(text), restkey="__extra__", restval=None)
    columns = [c.strip() for c in (rd.fieldnames or [])]
    if columns not in (ADV_KEPT, ADV_COLUMNS):        # the requested fields, or every field when they are not honoured
        raise ReadError(f"report {REPORT_ADVISORIES}: header changed: {rd.fieldnames}")
    rows, rejected = [], 0
    for r in rd:
        if not _valid(r, columns):
            rejected += 1
            continue
        rows.append({k: _clean(r.get(k)) for k in ADV_KEPT})
    return rows, rejected


def accept(rows: list[dict], rejected: int) -> list[dict]:
    """The rows of a read, or ReadError when it has none or too many malformed rows."""
    if not rows:
        raise ReadError(f"report {REPORT_ADVISORIES}: no valid rows ({rejected} malformed)")
    if rejected > MAX_REJECTED or rejected > MAX_REJECTED_SHARE * (len(rows) + rejected):
        raise ReadError(f"report {REPORT_ADVISORIES}: {rejected} malformed rows of {len(rows) + rejected}")
    return rows


def parse_advisories(text: str) -> list[dict]:
    return accept(*read_advisories(text))


def parse_sites(text: str) -> dict[str, dict]:
    """Report 2081 by Beach ID, SITE_FIELDS only, points rounded."""
    rd = csv.DictReader(io.StringIO(text))
    missing = [c for c in SITE_FIELDS if c not in (rd.fieldnames or [])]
    if missing:
        raise ReadError(f"report {REPORT_SITES}: columns missing: {missing}")
    out = {}
    for r in rd:
        s = {v: _clean(r.get(k)) or None for k, v in SITE_FIELDS.items()}
        try:                                      # a point is both coordinates or none (Astra review P2-3)
            s["lat"], s["lon"] = round(float(s["lat"]), POINT_DECIMALS), round(float(s["lon"]), POINT_DECIMALS)
        except (TypeError, ValueError):
            s["lat"] = s["lon"] = None
        if s["lat"] is not None and not (40 <= s["lat"] <= 49 and -91.5 <= s["lon"] <= -81):
            s["lat"] = s["lon"] = None            # a point outside Michigan's box is not used
        if s["beach_id"]:
            out[s["beach_id"]] = s
    if not out:
        raise ReadError(f"report {REPORT_SITES}: no sites")
    return out


def parse_date(v) -> date | None:
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\b", _clean(v))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def zone_of(site: dict | None) -> str:
    county = str((site or {}).get("county") or "").strip().upper()
    return zones.CENTRAL if county in MI_CENTRAL_COUNTIES else zones.EASTERN


def _sig(r: dict) -> list:
    return [r.get(k) for k in ADV_KEPT]


def _order(r: dict):
    return ((parse_date(r["EndDate"]) or date.max).isoformat(), r["Reason"], r["PollutionSource"],
            r["IssuingOrganization"])


def _suffix(key: str, base: str) -> int:
    return 1 if key == base else int(key[len(base) + 1:])


def keyed(rows: list[dict], state: dict | None = None) -> list[tuple[str, dict]]:
    """(source_record_id, row) for each distinct advisory (module docstring: Key). The ids of rows that share a key
    are kept in state["collision_ids"] (key -> the row's kept fields), so a correction of one row never moves its id
    to the other (Astra review 2026-11-21 P2-4): exact matches keep their ids, a changed row takes the id left free,
    a new row the next suffix."""
    assigned = state.setdefault("collision_ids", {}) if state is not None else {}
    seen, groups = set(), {}
    for r in rows:
        sig = tuple(_sig(r))
        if sig in seen:
            continue
        seen.add(sig)
        start = parse_date(r["StartDate"])
        code = TYPES.get(r["AdvisoryType"].lower(), ("beach_advisory", "advisory"))[1]
        base = f"{r['Identifier'] or 'noid'}-{start.strftime('%Y%m%d') if start else 'nodate'}-{code}"
        groups.setdefault(base, []).append(r)
    out = []
    for base, rs in groups.items():
        prev = assigned.get(base) or {}
        if len(rs) == 1 and not prev:
            out.append((base, rs[0]))
            continue
        left, used = sorted(rs, key=_order), {}
        for key in sorted(prev, key=lambda k: _suffix(k, base)):
            hit = next((r for r in left if _sig(r) == prev[key]), None)
            if hit is not None:
                used[key] = hit
                left.remove(hit)
        for key in sorted((k for k in prev if k not in used), key=lambda k: _suffix(k, base)):
            if left:
                used[key] = left.pop(0)
        n = max([_suffix(k, base) for k in list(prev) + list(used)], default=0)
        for r in left:
            n += 1
            used[base if n == 1 else f"{base}-{n}"] = r
        # every id keeps its row, present or not, so a row absent for a read gets its own id back (re-review P2)
        assigned[base] = {**prev, **{k: _sig(r) for k, r in used.items()}}
        out.extend(sorted(used.items(), key=lambda kv: _suffix(kv[0], base)))
    return out


def to_record(key: str, r: dict, site: dict | None, fetched_at: str, first_seen: str) -> dict:
    et, _code = TYPES.get(r["AdvisoryType"].lower(), ("beach_advisory", "advisory"))
    tz_name = zone_of(site)
    start, end = parse_date(r["StartDate"]), parse_date(r["EndDate"])
    raw = {"identifier": r["Identifier"] or None, "beach": r["Name"] or None, "advisory_type": r["AdvisoryType"] or None,
           "reason": r["Reason"] or None, "pollution_source": r["PollutionSource"] or None,
           "days_under_advisory": _days(r["DaysUnderAdvisory"]), "issuer": r["IssuingOrganization"] or None,
           "time_zone": tz_name, "state": "MI", "_first_seen_at": first_seen,
           "start_basis": "the advisory's start date as EGLE's MiEnviro beach export lists it (no time of day)"}
    if r["AdvisoryType"].lower() not in TYPES:
        raw["type_unmapped"] = f"advisory type {r['AdvisoryType']!r} read as a beach advisory"
    if site:
        raw.update(county=site.get("county"), access=site.get("access"), great_lake=site.get("great_lake"),
                   epa_beach_id=site.get("epa_beach_id"), park=site.get("park"))
    if end and start and end < start:
        raw["end_not_used"] = f"EGLE's end date {end.isoformat()} is before the start"
        end = None
    now_local = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).astimezone(ZoneInfo(tz_name)).date()
    lifted = end is not None and end < now_local          # an end's local day is over at the read
    if end is None:
        # the export is EGLE's archive table and gives no update time: an open row is EGLE's record as entered at its
        # start, not a fresh confirmation, so no _last_seen_in_source (build/status.py ages a beach advisory
        # CONFIRM_DAYS after its last confirmation, here its start, then shows it as not re-confirmed)
        raw["no_end_in_source"] = True
    water = (site or {}).get("waterbody")
    park = (site or {}).get("park")
    beach = r["Name"] if not park or park == r["Name"] else f"{r['Name']} - {park}"
    lat, lon = (site or {}).get("lat"), (site or {}).get("lon")
    org = r["IssuingOrganization"]
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=et,
        status="advisory_lifted" if lifted else "advisory_active",
        waterbody_text=None if not water or GENERIC_WATER.match(water) else water,
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=start.isoformat() if start else None, ended_at=end.isoformat() if end else None,
        time_precision="day", reported_at=None, published_at=None, source_updated_at=None, fetched_at=fetched_at,
        authority=(f"{org} (Michigan EGLE beach monitoring)" if org else CREDIT) + f": {r['AdvisoryType'] or 'advisory'}",
        outfall_name=beach or None, advice_text=None, source_url=MAP_PAGE, raw=raw,
        parse_error=None if start else f"no start date in {r['StartDate']!r}")


def build(rows: list[dict], sites: dict[str, dict], state: dict, fetched_at: str) -> tuple[list[dict], dict]:
    first = state.setdefault("first_seen", {})
    recs, no_site = [], 0
    for key, r in keyed(rows, state):
        site = sites.get(r["Identifier"])
        if site is None:
            no_site += 1
        first.setdefault(key, fetched_at)
        recs.append(to_record(key, r, site, fetched_at, first[key]))
    recs.sort(key=lambda x: (x["started_at"] or "", x["event_id"]), reverse=True)
    year = fetched_at[:4]
    this_year = [x for x in recs if (x["started_at"] or "").startswith(year)]
    meta = {
        "registry_ids": [SOURCE_ID], "export": EXPORT, "reports": {"advisories": REPORT_ADVISORIES, "sites": REPORT_SITES},
        "credit": CREDIT, "rows_read": len(rows), "advisories": len(recs), "no_site": no_site,
        "in_effect": sum(1 for x in recs if x["status"] == "advisory_active"),
        "no_end_in_source": sum(1 for x in recs if x["raw"].get("no_end_in_source")),
        f"begun_{year}": len(this_year),
        f"by_reason_{year}": dict(sorted(_count(x["raw"].get("reason") for x in this_year).items())),
        "time_note": "Dates only: EGLE's export gives the start and end day of each advisory, no time of day and no "
                     "posting time.",
    }
    return recs, meta


def _days(v):
    """EGLE's DaysUnderAdvisory ("5.0000000000") as a number, or None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 2)


def _count(vals) -> dict:
    out = {}
    for v in vals:
        out[v or "none"] = out.get(v or "none", 0) + 1
    return out


def distinct(rows: list[dict]) -> int:
    return len({tuple(_sig(r)) for r in rows})


def check_rows(rows: list[dict], state: dict) -> None:
    """The floor and the drop check, on distinct advisories (Astra review P1: 3,655 copies of one row are one)."""
    n, prev = distinct(rows), int(state.get("last_rows") or 0)
    if n < MIN_ROWS:
        raise ReadError(f"report {REPORT_ADVISORIES}: {n} distinct advisories, under the floor of {MIN_ROWS}")
    if prev and n < MIN_SHARE * prev:
        raise ReadError(f"report {REPORT_ADVISORIES}: {n} distinct advisories against {prev} at the last good read")


def load_sites(sess, rows: list[dict], fetched_at: str) -> dict[str, dict]:
    saved = read_json(SITES_PATH, {}) or {}
    sites = saved.get("sites") or {}
    at = saved.get("fetched_at")
    stale = not at or (datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                       - datetime.fromisoformat(at.replace("Z", "+00:00"))) > timedelta(hours=SITES_MAX_AGE_H)
    unknown = any(r["Identifier"] and r["Identifier"] not in sites for r in rows)
    if sites and not stale and not unknown:
        return sites
    try:
        fresh = parse_sites(fetch_report(sess, REPORT_SITES))
        floor = max(MIN_SITES, int(MIN_SHARE * len(sites)))      # a cut answer never replaces the list (review P2-2)
        if len(fresh) < floor:
            raise ReadError(f"report {REPORT_SITES}: {len(fresh)} sites, under {floor}")
    except (requests.RequestException, ReadError, ValueError, TypeError, OSError) as e:
        if sites:                       # the saved list still places what it knows
            print(f"{SOURCE_ID}: sites not refreshed ({type(e).__name__}); using the list of {at}", file=sys.stderr)
            return sites
        raise
    merged = {**sites, **fresh}          # a beach the answer lacks keeps its saved point (re-review: never dropped)
    write_json(SITES_PATH, {"fetched_at": fetched_at, "report": REPORT_SITES, "sites": merged})
    return merged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--advisories", help="a saved report 2082 CSV (with --sites and --out; no network)")
    ap.add_argument("--sites", help="a saved report 2081 CSV")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.advisories:
        if not (a.sites and a.out):
            ap.error("--advisories needs --sites and --out (only live reads reach the state file)")
        out = Path(a.out)
        st_path = out.with_suffix(".state.json")
        state = read_json(st_path, {}) or {}
        rows = parse_advisories(Path(a.advisories).read_text(encoding="utf-8-sig"))
        sites = parse_sites(Path(a.sites).read_text(encoding="utf-8-sig"))
        recs, meta = build(rows, sites, state, now)
        write_json(st_path, state)
        write_events(SOURCE_ID, recs, meta=meta, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records (files) -> {out}")
        return 0
    sess = requests.Session()
    sess.headers.update(HEADERS)
    state = read_json(STATE_PATH, {}) or {}
    try:
        rows, rejected = read_advisories(fetch_report(sess, REPORT_ADVISORIES, ADV_KEPT))
        accept(rows, rejected)
        check_rows(rows, state)
        sites = load_sites(sess, rows, now)
    except (requests.RequestException, ReadError, ValueError, TypeError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"export: {error_detail(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(rows), "json")        # the kept fields only: AdvisoryComments never reaches it
    recs, meta = build(rows, sites, state, now)
    meta["rows_rejected"] = rejected
    state["last_rows"] = distinct(rows)
    state["last_ok_at"] = now
    write_json(STATE_PATH, state)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} advisories ({meta['in_effect']} in effect) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
