"""Ohio Department of Health BeachGuard, current advisories -> data/build/events/oh-odh-beachguard.json.

Source (registry oh-odh-beachguard; research/oh/report.md section 2.5)
  The JSON behind BeachGuard's public pages: https://publicapps.odh.ohio.gov/beachguardpublic/api/advisorieslist with
  queryParams {"filter":[{"isCurrentAdvisory":true}]}: one row per advisory in effect at a public or private bathing
  beach, entered by the issuing organisation (a local health district, the Ohio Department of Natural Resources).
  Fields read (SAFE_FIELDS): id (the advisory's own id), beachId, beachName, beachAccessTypeId, parkName,
  waterBodyName, waterBodyTypeId, countyName, issuingOrganizationName, typeId, typeText, typeSeverityLevel,
  reasonTypeText, pollutionSourceTypeText, startDate ("05/20/2026 11:10 AM", Ohio's wall clock), reopenDate
  ("Ongoing" or a date), comment (free text, scrubbed: below), latitudeCenter, longitudeCenter. Excluded: metadata and
  thisObject (the API's own scaffolding), the lookup ids (countyId, issuingOrganizationId, reasonTypeId,
  pollutionSourceTypeId), daysUnderAdvisory (derived from the start) and isCurrentAdvisory (the filter).
  The list of past advisories is not read: the API refuses it whole ("A JSON string exceeds the maximum allowed
  number of characters", 2026-11-08) and offers no paging; the archive grows from the polls.
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
  - Place: the beach's centre point (coord_source source), waterbody_text the water body's name (a bare "Lake" or
    "Pond" is none); raw.county; authority the issuing organisation "(Ohio BeachGuard)". A point is a marker; the
    status build draws no whole-water colour from it beyond its rules.
  Privacy: only SAFE_FIELDS are kept and the raw save holds only them; the comment runs through Illinois's
  BeachGuard scrub (il_idph_beachguard.scrub_comment: a name after "call" or "contact", then
  mi_egle_mienviro.free_text) before it is stored, with measurements ("252 cfu/100mL") shielded from the address
  rule; common.event runs strip_personal.

State: data/build/oh-odh-beachguard-state.json (every advisory seen): the archive, do not delete.
Run from pipeline/: python -m ingest.oh_odh_beachguard [--file saved.json --out events.json]
Cadence: hourly with the refresh.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "oh-odh-beachguard"
API = "https://publicapps.odh.ohio.gov/beachguardpublic/api/advisorieslist"
QUERY = '{"filter":[{"isCurrentAdvisory":true}]}'
PAGE_URL = "https://publicapps.odh.ohio.gov/beachguardpublic/"
SAFE_FIELDS = ["id", "beachId", "beachName", "beachAccessTypeId", "parkName", "waterBodyName", "waterBodyTypeId",
               "countyName", "issuingOrganizationName", "typeId", "typeText", "typeSeverityLevel", "reasonTypeText",
               "pollutionSourceTypeText", "startDate", "reopenDate", "comment", "latitudeCenter", "longitudeCenter"]
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
STATE_PATH = BUILD_DIR / "oh-odh-beachguard-state.json"
EMPTY_POLLS_TO_LIFT = 2
CREDIT = "Ohio Department of Health, BeachGuard"
GENERIC_WATER = re.compile(r"^(lake|pond|beach|river|reservoir|quarry)$", re.I)


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


def start_time(text) -> str | None:
    try:
        return datetime.strptime(str(text or "").strip(), "%m/%d/%Y %I:%M %p").replace(tzinfo=TZ).isoformat()
    except ValueError:
        return None


# a measurement ("252 cfu/100mL", "8.2 ug/L") is no house number: shielded from the address scrub, then restored
MEASURE = re.compile(r"(?i)\b\d+(?:\.\d+)?(?=\s*(?:cfu|mpn|colonies|ug/?l|\u00b5g/?l|ppb|mg/?l|cells|%))")


def clean_comment(v) -> str | None:
    if not v or not str(v).strip():
        return None
    from ingest.il_idph_beachguard import scrub_comment      # a name after a contact cue, then the full scrub
    text = " ".join(str(v).split())
    kept = MEASURE.findall(text)
    out = scrub_comment(MEASURE.sub("\u2063MEASURE\u2063", text)) or ""
    for m in kept:
        out = out.replace("\u2063MEASURE\u2063", m, 1)
    return out


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


def to_record(key: str, r: dict) -> dict:
    a = r["row"]
    et, mapped = event_type_of(a.get("typeId"), a.get("typeText"))
    lifted = r.get("lifted_at")
    water = a.get("waterBodyName")
    raw = {"advisory": {k: v for k, v in a.items() if k not in ("latitudeCenter", "longitudeCenter")},
           "county": a.get("countyName"), "time_zone": TZ_NAME, "state": "OH",
           "_first_seen_at": r["first_listed_at"], "_last_seen_in_source": r["last_listed_at"],
           "start_basis": "the advisory's start date as BeachGuard lists it"}
    if a.get("reopenDate") and str(a["reopenDate"]).strip().lower() != "ongoing":
        raw["reopen_note"] = f"BeachGuard listed a reopening date of {a['reopenDate']}; it is not used as the end"
    if not mapped:
        raw["type_unmapped"] = f"advisory type {a.get('typeId')!r} read as a beach advisory"
    if lifted:
        raw.update(ended_at_precision="poll", lift_observed_between=r["lift_between"],
                   lift_basis="BeachGuard's list of current advisories stopped listing it")
    reason = "; ".join(x for x in (a.get("reasonTypeText"),
                                   f"source: {a['pollutionSourceTypeText']}" if a.get("pollutionSourceTypeText") else None,
                                   a.get("comment")) if x)
    raw["reason"] = reason or None
    beach = " - ".join(x for x in (a.get("beachName"), a.get("parkName")) if x)
    org = a.get("issuingOrganizationName")
    lat, lon = a.get("latitudeCenter"), a.get("longitudeCenter")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=et,
        status="advisory_lifted" if lifted else "advisory_active",
        waterbody_text=None if not water or GENERIC_WATER.match(water) else water,
        lat=lat if isinstance(lat, (int, float)) else None, lon=lon if isinstance(lon, (int, float)) else None,
        coord_source="source" if isinstance(lat, (int, float)) else None,
        started_at=start_time(a.get("startDate")), ended_at=lifted, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=r["last_listed_at"],
        authority=(f"{org} (Ohio BeachGuard)" if org else CREDIT) + (f": {a['typeText']}" if a.get("typeText") else ""),
        outfall_name=beach or None,
        advice_text=a.get("comment") or None,   # the issuer's own words only; the type and reason are in raw
        source_url=PAGE_URL, raw=raw)


def run(state: dict, rows: list[dict], now: str) -> tuple[list[dict], dict]:
    counts = apply(state, rows, now)
    state["last_poll"] = {"at": now, "listed": len(rows), **counts}
    recs = [to_record(k, r) for k, r in state["records"].items()]
    recs.sort(key=lambda x: (x["started_at"] or "", x["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "api": API, "poll": state["last_poll"], "credit": CREDIT,
            "time_note": "Start dates are BeachGuard's (Eastern time); a lift is the first poll that no longer listed "
                         "the advisory."}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="a saved API answer (needs --out; its state is kept next to that file)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out:
            ap.error("--file needs --out (only live polls reach the archive)")
        out = Path(a.out)
        st_path = out.with_suffix(".state.json")
        state = read_json(st_path, {}) or {}
        recs, meta = run(state, rows_of(json.loads(Path(a.file).read_text())), now)
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
        write_events(SOURCE_ID, [], ok=False, error=f"API: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(rows), "json")
    recs, meta = run(state, rows, now)
    write_json(STATE_PATH, state)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records, {len(rows)} listed now -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
