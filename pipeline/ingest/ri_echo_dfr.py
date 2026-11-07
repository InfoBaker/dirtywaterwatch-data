"""EPA ECHO detailed facility reports for Rhode Island wastewater permits: single-event violations
that are sewer overflows or bypasses.

Source: https://echodata.epa.gov/echo/dfr_rest_services.get_dfr?p_id=<permit>&output=JSON, one request
per permit for the NPDES permits listed in research/ri/dischargers.json (20 individual permits;
the collection-system rows there have no permit of their own), with a 2 s pause between requests.
U.S. government data; ECHO asks to be cited. Raw responses go to data/raw/ri-echo-dfr/.

What is used: Results.CWASECompliance.Sources[].Violations[] (ViolationDesc, NPDESViolationId,
SourceID, Agency, Qtr1..13Value = the event date "MM/DD/YYYY" or range "MM/DD/YYYY-MM/DD/YYYY",
"--->" when the violation carries into the next quarter) for a rolling 13 quarters, and
SystemExtractDates (ICIS-NPDES extract date). SBEEventTotals (yearly counts and gallons) go to meta
only. Violations whose description is not an overflow or bypass (operation and maintenance,
late reports) are skipped and counted in meta.

Record rules (nothing is invented):
- event_type: "bypass" for unanticipated bypasses, "sso" for SSOs, "cso" for (dry-weather) CSOs.
  Status "ended"; started_at = first date, ended_at = second date of a range, null for a single
  date (ECHO does not give the end); time_precision "day" (00:00 America/New_York).
- No volume (ECHO gives none per event): volume_gal null. No outfall, no location.
- Water placement: a bypass happens at the treatment plant, so it is placed on the plant's
  receiving water (the permit's treated-effluent outfall in data/outfalls-new-england.json, else the first
  water in research/ri/dischargers.json), water_match "inferred". SSOs and CSOs can be anywhere in
  the sewer system: water_slugs [] (the discharger's waters are in raw). Violations described as
  "no discharge to waters of the U.S." are kept, with water_slugs [] and raw.reached_water false.
  raw.water_basis says how in words; the files behind it are named in meta.water_basis_files, never
  in raw (raw is the public source record), and any other note naming a repository file moves to
  meta.internal_notes (common.path_notes_to_meta).
- published_at = the ICIS-NPDES extract date of the first pull that contained the record (kept
  across runs; for records already present on the first pull it is an upper bound).
  raw.note: "appeared in EPA ECHO; not a public notice". authority "EPA ECHO (reported to regulators)".

Quirks: ECHO lists only events coded as violations, so routine permitted wet-weather CSOs never
appear; SBE totals and violation lists do not always agree; the lag behind the event is days to
weeks (5-day NeT-SewerOverflow report, then state review). A permit whose request fails keeps its
previous records.

Cadence: weekly (the ICIS-NPDES extract is weekly).

Run: python -m ingest.ri_echo_dfr [--from-raw]   (from pipeline/; --from-raw re-parses the latest saved
responses without calling ECHO)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from common import (DATA_DIR, EVENTS_DIR, HEADERS, RAW_DIR, ROOT, event, now_iso, path_notes_to_meta, read_json,
                    save_raw, write_events)

SOURCE_ID = "ri-echo-dfr"
DFR_URL = "https://echodata.epa.gov/echo/dfr_rest_services.get_dfr"
PAGE_URL = "https://echo.epa.gov/detailed-facility-report?fid={permit}"
AUTHORITY = "EPA ECHO (reported to regulators)"
NOTE = "appeared in EPA ECHO; not a public notice"
# the files the plant's receiving water comes from (meta, not raw)
WATER_BASIS_FILES = {"treated_effluent_outfalls": "data/outfalls-new-england.json", "first_receiving_water": "research/ri/dischargers.json"}
TZ = ZoneInfo("America/New_York")
PAUSE_S = 2.0
OVERFLOW_RE = re.compile(r"\b(SSO|CSO|bypass|overflow|spill)\b", re.I)
PAPERWORK_RE = re.compile(r"^\s*PR:|failure to (submit|report|notify)", re.I)  # reporting violations, not events


def permits() -> list[dict]:
    rows = read_json(ROOT / "research" / "ri" / "dischargers.json", []) or []
    return [r for r in rows if r.get("npdes_permit")]


def plant_waters(permit: str, discharger: dict, registry: list[dict]) -> tuple[list[str], str]:
    """The plant's receiving water and how it was found, in words (no file names: they are in
    WATER_BASIS_FILES, written to meta)."""
    tcs = [o for o in registry if o["npdes_permit"] == permit and o.get("outfall_status") == "TCS" and o.get("water_slug")]
    if tcs:
        slugs = list(dict.fromkeys(o["water_slug"] for o in tcs))
        return slugs, f"the permit's treated-effluent outfall(s) {', '.join(o['outfall'] for o in tcs)} in EPA's outfall records"
    slugs = (discharger.get("water_slugs") or [])[:1]
    return slugs, "the discharger's first listed receiving water" if slugs else "none known"


def day_iso(s: str) -> str:
    d = datetime.strptime(s.strip(), "%m/%d/%Y")
    return d.replace(tzinfo=TZ).isoformat()


def classify(desc: str) -> str:
    d = desc.lower()
    if "bypass" in d:
        return "bypass"
    if re.search(r"\bsso\b|sanitary sewer overflow", d):
        return "sso"
    if re.search(r"\bcso\b|combined sewer overflow", d):
        return "cso"
    return "unknown"


def violation_dates(v: dict, header: dict) -> tuple[str | None, str | None, list]:
    vals = []
    for i in range(1, 14):
        val = v.get(f"Qtr{i}Value")
        if val:
            vals.append({"quarter": i, "start": header.get(f"Qtr{i}Start"), "end": header.get(f"Qtr{i}End"),
                         "value": val, "status": v.get(f"Qtr{i}Status")})
    for q in vals:
        m = re.fullmatch(r"\s*(\d{2}/\d{2}/\d{4})(?:\s*-\s*(\d{2}/\d{2}/\d{4}))?\s*", q["value"])
        if m:
            return m.group(1), m.group(2), vals
    return None, None, vals


def link_nbc(records: dict) -> None:
    """NBC overflows appear both on NBC's map (ri-nbc) and here: note the ri-nbc events on the same
    permit that started within the ECHO date range, so the two can be shown as one occurrence."""
    nbc = (read_json(EVENTS_DIR / "ri-nbc.json", {}) or {}).get("records", [])
    for r in records.values():
        if r["event_type"] != "cso" or not r["started_at"]:
            continue
        lo = r["started_at"][:10]
        hi = (r["ended_at"] or r["started_at"])[:10]
        hits = [n["event_id"] for n in nbc if n.get("npdes_permit") == r["npdes_permit"]
                and n.get("started_at") and lo <= n["started_at"][:10] <= hi]
        r["raw"]["possible_matches"] = hits or None


def main(argv: list[str]) -> int:
    from_raw = "--from-raw" in argv
    s = requests.Session()
    s.headers.update(HEADERS)
    fetched = now_iso()
    prev_file = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = {r["event_id"]: r for r in prev_file.get("records", [])}
    registry = (read_json(DATA_DIR / "outfalls-new-england.json", {}) or {}).get("outfalls", [])
    records, errors, totals, skipped, extract_dates = {}, {}, {}, {}, {}
    plist = permits()
    for n, d in enumerate(plist):
        permit = d["npdes_permit"]
        try:
            if from_raw:  # reprocess the latest saved response, no request
                files = sorted((RAW_DIR / SOURCE_ID).glob(f"*.{permit}.json"))
                if not files:
                    raise FileNotFoundError(f"no saved response for {permit}")
                res = json.loads(files[-1].read_text()).get("Results") or {}
            else:
                if n:
                    time.sleep(PAUSE_S)
                r = s.get(DFR_URL, params={"p_id": permit, "output": "JSON"}, timeout=120)
                r.raise_for_status()
                res = r.json().get("Results") or {}
                save_raw(SOURCE_ID, r.content, f"{permit}.json")
            if res.get("Message") not in (None, "Success") and not res.get("CWASECompliance"):
                raise ValueError(f"ECHO message: {res.get('Message')}")
        except Exception as e:
            errors[permit] = str(e)[:300]
            continue
        extract = next((x["SystemExtractDate"] for x in (res.get("SystemExtractDates") or {}).get("Dates", [])
                        if x.get("EPASystem") == "ICIS-NPDES"), None)
        extract_iso = day_iso(extract) if extract else None
        extract_dates[permit] = extract
        totals[permit] = [{k: v for k, v in row.items()} for src in (res.get("SBEEventTotals") or {}).get("Sources", [])
                          for row in src.get("SBEEvents", [])]
        se = res.get("CWASECompliance") or {}
        header = se.get("Header") or {}
        pslugs, pbasis = plant_waters(permit, d, registry)
        for src in se.get("Sources") or []:
            for v in src.get("Violations") or []:
                desc = (v.get("ViolationDesc") or "").strip()
                if not OVERFLOW_RE.search(desc) or PAPERWORK_RE.search(desc):
                    skipped.setdefault(desc, 0)
                    skipped[desc] += 1
                    continue
                vid = v.get("NPDESViolationId") or f"{permit}-{v.get('SourceID')}-" + hashlib.sha1(
                    json.dumps(v, sort_keys=True).encode()).hexdigest()[:10]
                start, end, quarters = violation_dates(v, header)
                etype = classify(desc)
                reached = not re.search(r"no discharge to waters", desc, re.I)
                bypass_on_water = etype == "bypass" and reached and bool(pslugs)
                eid = f"{SOURCE_ID}:{vid}"
                old = prev.get(eid)
                published = (old or {}).get("published_at") or extract_iso
                parse_error = None if start else f"no event date in quarters: {[q['value'] for q in quarters]}"
                raw = {
                    "SourceID": v.get("SourceID"), "ViolationDesc": desc, "NPDESViolationId": v.get("NPDESViolationId"),
                    "Agency": v.get("Agency"), "quarters": quarters, "icis_extract_date": extract,
                    "weather": "wet" if desc.lower().startswith("wet") else "dry" if desc.lower().startswith("dry") else None,
                    "reached_water": reached, "note": NOTE,
                    "published_at_basis": "ICIS-NPDES extract date of the first ECHO pull that contained this record"
                                          + ("" if old else " (upper bound when present on the first pull)"),
                    "end_note": None if end else "ECHO gives one date; the end is not stated",
                    "water_basis": ("bypass at the treatment plant; plant receiving water: " + pbasis) if bypass_on_water else
                                   ("no discharge to waters reported" if not reached else
                                    "location not given by ECHO (sewer system); discharger's waters: "
                                    + ", ".join(d.get("receiving_waters") or [])),
                    "continues_next_quarter": any(q["value"].strip() == "--->" for q in quarters),
                }
                rec = event(
                    source_id=SOURCE_ID, source_record_id=str(vid),
                    event_type=etype if start else "unknown", status="ended",
                    discharger_id=d.get("id"), discharger_name=d.get("name"), npdes_permit=permit,
                    waterbody_text=", ".join(d.get("receiving_waters") or [])[:200] if bypass_on_water else None,
                    water_slugs=pslugs if bypass_on_water else [], water_match="inferred" if bypass_on_water else "none",
                    started_at=day_iso(start) if start else None, ended_at=day_iso(end) if end else None,
                    time_precision="day", reported_at=None, published_at=published, source_updated_at=extract_iso,
                    fetched_at=fetched, volume_gal=None, estimate_flag="unknown", authority=AUTHORITY,
                    source_url=PAGE_URL.format(permit=permit), raw=raw, parse_error=parse_error,
                )
                records[rec["event_id"]] = rec
    if len(errors) == len(plist):
        write_events(SOURCE_ID, [], ok=False, error=f"all {len(plist)} permits failed: {next(iter(errors.values()))}")
        print(f"ri-echo-dfr: FAILED {errors}", file=sys.stderr)
        return 1
    link_nbc(records)
    kept = 0
    for eid, r in prev.items():  # failed permits and violations that aged out of the 13-quarter window
        if eid not in records:
            if r["npdes_permit"] not in errors:
                r["raw"] = {**r.get("raw", {}), "gone_from_echo_since": r["raw"].get("gone_from_echo_since") or fetched}
            records[eid] = r
            kept += 1
    out = sorted(records.values(), key=lambda r: r["started_at"] or "", reverse=True)
    meta = {"permits": len(plist), "permits_failed": errors or None, "records": len(out), "kept_from_previous": kept,
            "by_type": {t: sum(1 for r in out if r["event_type"] == t) for t in ("sso", "bypass", "cso", "unknown")},
            "with_water_slug": sum(1 for r in out if r["water_slugs"]),
            "skipped_violation_types": skipped, "icis_extract_dates": extract_dates, "sbe_event_totals": totals,
            "water_basis_files": WATER_BASIS_FILES}
    path_notes_to_meta(out, meta)          # kept records from older runs carried file paths in raw
    path = write_events(SOURCE_ID, out, ok=True, error=(f"{len(errors)} permit(s) failed" if errors else None), meta=meta)
    print(f"ri-echo-dfr: {len(out)} events from {len(plist) - len(errors)}/{len(plist)} permits {meta['by_type']}; "
          f"water slug {meta['with_water_slug']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
