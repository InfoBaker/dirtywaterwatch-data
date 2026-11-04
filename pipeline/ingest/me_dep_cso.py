"""Maine DEP CSO outfalls (MEPDES layer) and annual CSO totals (DEP CSO Status Report).

Sources
  1. MEPDES CSO outfall layer, gis.maine.gov .../dep/MainePollutantDischargeEliminationSystem/
     MapServer/2 (registry: me-dep-mepdes-cso-outfalls). 266 GPS points (active and closed) keyed by
     permit (NEPDES_FAC) + OUTFALL_ID, 'WITHIN 5M' mapping grade, licence 'No limitations'.
     Quirks: STATUS lags about two years (111 ACTIVE against 106 in the 2025 report: GAUD 008, KSTD
     003/005 and Old Town 003/004 closed in 2024-25 but still read ACTIVE); 12 rows have ACTIVE='Y'
     with STATUS='CLOSED'; Milford is ME0001678 in the layer but ME0102695 in DEP's report.
     -> data/build/me-cso-outfalls.json, with a per-permit reconciliation against the report's
     2025 outfall counts and the water slug from data/outfalls-ne.json where the ECHO inventory has
     the same permit + outfall.
  2. Maine Combined Sewer Overflow Status Report (registry: me-dep-cso-status-report), DEP's
     yearly PDF, the only public discharge record in Maine: per permittee, gallons and event-days
     (any calendar day with a discharge) per year. Text extracted to research/me/raw/
     me-cso-2025-status-report.txt (report dated June 30, 2026) and me-cso-2024-status-report.txt
     (June 30, 2025). Records: event_type annual_total, status ended, started_at Jan 1 and
     ended_at Dec 31 of the year (time_precision year), volume_gal, published_at = the report date.
     Years 2011-2025 come from the 2025 report (the 2024 report notes that earlier reports had
     misaligned prior-year columns, so the newest report is the corrected series). The 2024 column
     of the 2024 report is the first publication of the 2024 figures; where the 2025 report
     changed a 2024 figure (Bangor: block-trip events re-counted) the 2025 value is a revision
     record whose parent_event_id is the 2024-report record. The 2024 report's two-column table
     layout is scrambled in the text extraction; rows that do not parse cleanly fall back to
     TRANSCRIBED_2024 below (read by hand from that text). Combined rows (Portland & PWD, Bar Harbor
     main + Hulls Cove) stay one record under the first permit, with every permit in raw.permits.
     Rockland's row has 10 values for 15 year columns (blank cells, 'n/r'): its record carries
     volume_gal null and a parse_error. Former permittees (KSTD and Paris exited in 2024) have no
     2024 cell: the 442,000 gal sometimes read as Paris 2024 is its 2023 figure (the 2023 and 2024
     statewide totals only add up that way). The 2025 report's 'Former CSO Permittees' aggregate
     row has no permit and is not recorded.

Failures
  A failed layer request, a missing report text or any other failed part writes ok=False with the
  error (data/build/events keeps the previous records; me-cso-outfalls.json keeps the last good
  pull, marked ok false). Parse problems in the report tables are not run failures: they are
  records with parse_error, listed in meta.problems.

Lag and cadence
  The report appears each June-July for the previous calendar year (latency 6-18 months); poll
  the DEP reports index monthly in June-August, otherwise quarterly. The outfall layer is
  'updated as necessary' (last real update reflects end 2023); re-pull monthly.

Run from pipeline/:  python -m ingest.me_dep_cso
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import requests

from common import (DATA_DIR, BUILD_DIR, HEADERS, ROOT, event, now_iso, read_json, save_raw,
                    write_events, write_json)

SOURCE_ID = "me-dep-cso-annual"
OUTFALL_SOURCE_ID = "me-dep-mepdes-cso-outfalls"
LAYER_URL = ("https://gis.maine.gov/mapservices/rest/services/dep/MainePollutantDischargeEliminationSystem/"
             "MapServer/2")
QUERY = LAYER_URL + "/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=json"
RESEARCH = ROOT / "research" / "me"
AUTHORITY = "Maine DEP CSO Status Report"

def _report_text(name: str):
    """The extracted report text: the tracked copy in data/reference/ (the public data repository carries it), else
    the research raw folder on the machine that extracted it."""
    for p in (ROOT / "data" / "reference" / name, RESEARCH / "raw" / name):
        if p.exists():
            return p
    return ROOT / "data" / "reference" / name


REPORTS = [
    {"year": 2025, "text": _report_text("me-cso-2025-status-report.txt"), "published_at": "2026-06-30",
     "url": "https://www.maine.gov/dep/publications/documents/legislative%20reports/Maine%20CSO%202025%20Status%20Report.pdf",
     "title": "Maine Combined Sewer Overflow 2025 Status Report (June 2026)"},
    {"year": 2024, "text": _report_text("me-cso-2024-status-report.txt"), "published_at": "2025-06-30",
     "url": "https://www.maine.gov/dep/publications/reports/index.html",
     "title": "Maine Combined Sewer Overflow 2024 Status Report (June 2025)"},
]
FIRST_YEAR = 2011          # the report tables show 1987, 1988 and 2011 (2010) onward
PERMIT_ALIASES = {"ME0102695": ["ME0001678"]}   # Milford: report permit -> layer / ECHO permit

# 2024 report, 2024 column, for rows the text extraction interleaved (two-column layout).
# Read by hand from research/me/raw/me-cso-2024-status-report.txt; (gallons, event-days).
TRANSCRIBED_2024 = {
    "ME0100781": (72_999_979, 18),   # Bangor (2025 report revises to 73,011,955 / 16)
    "ME0101214": (3_179_664, 8),     # Bar Harbor ME0101214 & ME0102466
    "ME0100111": (0, 0),             # Bucksport (SWIRL, no CSO outfalls)
    "ME0100129": (1_975_800, 4),     # Calais
    "ME0102806": (492_425, 7),       # Cape Elizabeth
    "ME0100013": (10_679_193, 5),    # Greater Augusta U.D.
    "ME0102512": (158_730, 3),       # Hampden
    "ME0100994": (33_696_254, 17),   # Lewiston
    "ME0101435": (290_214_400, 48),  # Portland & PWD
    "ME0102423": (50_000, 2),        # Randolph
    "ME0101117": (4_027_000, 14),    # Saco
    "ME0100625": (2_448_510, 6),     # Skowhegan
    "ME0100633": (4_242_992, 5),     # South Portland
    "ME0100846": (7_843_700, 5),     # Westbrook
    "ME0102628": (7_361_250, 8),     # Winslow
    "ME0100749": (48_000, 2),        # Winterport
}

PERMIT_RE = re.compile(r"(?:City-|PWD-)?ME ?(\d{7})")
NUM = r"\d{1,3}(?:,\d{3})+|\d+"


# --------------------------------------------------------------------------- report tables

def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:j if j > 0 else None]


def parse_table(sec: str) -> tuple[list[int], dict[str, dict]]:
    """Header years and {first_permit: {"permits": [...], "label": str, "values": [int|None...]}}."""
    hdr = re.search(r"Permittee NPDES Permit No\.\s+((?:\d{4}\s+)+)", sec)
    years = [int(y) for y in hdr.group(1).split()] if hdr else []
    body = sec[hdr.end():] if hdr else sec
    flat = re.sub(r"\s+", " ", body)
    rows = {}
    # a row: label, one or more permits joined by & or /, then a run of numbers
    pat = re.compile(r"([A-Za-z][A-Za-z .&()\-–']*?)?\s*((?:(?:City-|PWD-)?ME ?\d{7}\s*(?:&|/)?\s*)+)"
                     rf"((?:(?:{NUM})\s+)*(?:{NUM}))(?=\s|$)")
    for m in pat.finditer(flat):
        permits = ["ME" + p for p in PERMIT_RE.findall(m.group(2))]
        vals = [int(v.replace(",", "")) for v in m.group(3).split()]
        label = re.sub(r"\s+", " ", (m.group(1) or "")).strip()
        rows.setdefault(permits[0], {"permits": permits, "label": label, "values": vals})
    return years, rows


def year_values(years: list[int], vals: list[int]) -> dict[int, int] | None:
    """Values by year when the row has one value per column; None when the count does not fit."""
    if len(vals) == len(years):
        return dict(zip(years, vals))
    return None


def load_report(rep: dict) -> dict:
    text = rep["text"].read_text(errors="replace")
    flow = section(text, "Maine CSO Permittee Flow Data\nPermittee", "Maine CSO Permittee Annual Number of CSO Discharge Events\nPermittee")
    evs = section(text, "Maine CSO Permittee Annual Number of CSO Discharge Events\nPermittee", "Total Number of CSO Discharge Events")
    fy, frows = parse_table(flow)
    ey, erows = parse_table(evs)
    out = {}
    for permit, r in frows.items():
        out[permit] = {"permits": r["permits"], "label": r["label"], "gal": year_values(fy, r["values"]),
                       "gal_raw": r["values"], "days": None, "days_raw": None}
    for permit, r in erows.items():
        o = out.setdefault(permit, {"permits": r["permits"], "label": r["label"], "gal": None, "gal_raw": None})
        o["days"] = year_values(ey, r["values"])
        o["days_raw"] = r["values"]
    return {"years": fy, "rows": out}


# --------------------------------------------------------------------------- outfall layer

def fetch_layer() -> tuple[list[dict], str, str | None]:
    """(features, how, error). On failure the research copy stands in for slug matching only."""
    try:
        r = requests.get(QUERY, headers=HEADERS, timeout=90)
        r.raise_for_status()
        js = r.json()
        if not isinstance(js, dict) or not js.get("features"):
            raise ValueError(f"no features: {str(js)[:200]}")
        save_raw(OUTFALL_SOURCE_ID, r.content, "json")
        return js["features"], "live", None
    except (requests.RequestException, ValueError) as e:
        p = RESEARCH / "raw" / "mepdes_cso_all.json"
        err = f"MEPDES CSO layer: {type(e).__name__}: {e}"
        print(f"warn: {err}; using {p} for water matching", file=sys.stderr)
        return (read_json(p, {}) or {}).get("features", []), "research copy", err


def registry_index() -> dict[tuple[str, str], dict]:
    reg = read_json(DATA_DIR / "outfalls-ne.json", {}) or {}
    return {(o["npdes_permit"], str(o["outfall"]).zfill(3)): o for o in reg.get("outfalls", [])}


def me_waters_by_name() -> dict[str, list[dict]]:
    import csv
    out: dict[str, list[dict]] = defaultdict(list)
    with open(DATA_DIR / "waters-ne.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["state"] == "ME":
                out[re.sub(r"[^a-z0-9]+", " ", r["name"].lower()).strip()].append(r)
    return out


FLOWING = re.compile(r"\b(river|stream|brook|creek)\b", re.I)
STILL = {"lake", "pond", "reservoir"}


ME_BBOX = {w["slug"]: w.get("bbox") for w in (read_json(DATA_DIR / "waters-me.json", {}) or {}).get("waters", [])}


def outfall_water(permit, outfall, waterbody, reg, by_name, lat=None, lon=None) -> tuple[str | None, str]:
    """Registry slug when the ECHO inventory has this permit + outfall and the kinds agree (a river
    outfall is not put on a lake of the same name); else the DEP WATERBODY name when exactly one
    Maine water has it."""
    r = reg.get((permit, (outfall or "").zfill(3))) if permit and outfall else None
    if r and r.get("water_slug"):
        if not (r.get("water_kind") in STILL and FLOWING.search(waterbody or "")):
            return r["water_slug"], "outfall_registry"
    key = re.sub(r"[^a-z0-9]+", " ", (waterbody or "").lower()).strip()
    hits = by_name.get(key, [])
    if lat is not None and lon is not None:   # a same-named water elsewhere in Maine is not this one
        hits = [h for h in hits if (b := ME_BBOX.get(h["slug"])) and b[0] - .03 <= lon <= b[2] + .03
                and b[1] - .03 <= lat <= b[3] + .03]
    if len(hits) == 1:
        return hits[0]["slug"], "name"
    return None, "none"


def build_outfalls(features: list[dict], how: str, report_counts: dict[str, int]) -> list[dict]:
    reg = registry_index()
    by_name = me_waters_by_name()
    alias_rev = {a: k for k, v in PERMIT_ALIASES.items() for a in v}
    out = []
    for f in features:
        a = f.get("attributes") or {}
        g = f.get("geometry") or {}
        permit = (a.get("NEPDES_FAC") or "").replace(" ", "") or None
        outfall = (a.get("OUTFALL_ID") or "").strip() or None
        try:
            lat, lon = float(a.get("LATITUDE")), float(a.get("LONGITUDE"))
        except (TypeError, ValueError):
            lat, lon = g.get("y"), g.get("x")
        r = reg.get((permit, (outfall or "").zfill(3))) if permit and outfall else None
        slug, smatch = outfall_water(permit, outfall, a.get("WATERBODY"), reg, by_name, lat, lon)
        out.append({
            "water_slug": slug, "water_match": smatch,
            "permit": permit, "report_permit": alias_rev.get(permit, permit), "outfall": outfall,
            "masterid": a.get("MASTERID"), "name": (a.get("OUTFALL_NA") or "").strip() or None,
            "facility": (a.get("FACILITY_N") or "").strip() or None,
            "waterbody": (a.get("WATERBODY") or "").strip() or None,
            "lat": lat, "lon": lon, "status": a.get("STATUS"), "active_flag": a.get("ACTIVE"),
            "comment": (a.get("COMMENT") or "").strip() or None,
            "location_accuracy": a.get("LOCATION_A"), "location_method": a.get("LOCATION_M"),
            "maine_licence": a.get("MAINE_LICE"),
            "echo_outfall_status": (r or {}).get("outfall_status"),
            "echo_water_match": (r or {}).get("match"),
        })
    out.sort(key=lambda o: (o["permit"] or "", o["outfall"] or ""))
    return out


# --------------------------------------------------------------------------- records

def dischargers() -> dict[str, dict]:
    rows = read_json(RESEARCH / "dischargers.json", []) or []
    rows = rows if isinstance(rows, list) else rows.get("dischargers", [])
    return {r["npdes_permit"]: r for r in rows if r.get("npdes_permit")}


def waters_for(permits: list[str], outfalls: list[dict], disc: dict) -> tuple[list[str], str, str | None]:
    want = set(permits) | {a for p in permits for a in PERMIT_ALIASES.get(p, [])}
    act = [o for o in outfalls if o["permit"] in want and o["status"] == "ACTIVE"]
    slugs = sorted({o["water_slug"] for o in act if o["water_slug"]})
    names = sorted({re.sub(r"\s+", " ", o["waterbody"]).title() for o in act if o["waterbody"]})
    if slugs:
        how = "outfall_registry" if any(o["water_match"] == "outfall_registry" for o in act) else "name"
        return slugs, how, "; ".join(names) or None
    ds = sorted({s for p in permits for s in (disc.get(p, {}).get("water_slugs") or [])})
    if not names:
        names = sorted({w for p in permits for w in (disc.get(p, {}).get("receiving_waters") or [])})
    return ds, ("name" if ds else "none"), "; ".join(names) or None


def make_record(*, permit_row: dict, year: int, gal, days, rep: dict, outfalls, disc, key_suffix="",
                parent=None, note=None, parse_error=None) -> dict:
    permits = permit_row["permits"]
    p0 = permits[0]
    d = disc.get(p0, {})
    names = [disc.get(p, {}).get("name") for p in permits if disc.get(p, {}).get("name")]
    slugs, how, wtext = waters_for(permits, outfalls, disc)
    if gal is None:
        vtext = "not reported in the report table"
    else:
        vtext = f"{gal:,} gallons in {year}" + (f" over {days} event-day(s)" if days is not None else "")
        if len(permits) > 1:
            vtext += " (combined figure for " + " and ".join(permits) + ")"
    raw = {"report": rep["title"], "report_year": rep["year"], "table_label": permit_row["label"],
           "permits": permits, "year": year, "gallons": gal, "event_days": days,
           "event_day_definition": "any calendar day on which one or more CSO locations within a community experience a discharge"}
    if note:
        raw["note"] = note
    return event(
        source_id=SOURCE_ID, source_record_id=f"{p0}:{year}{key_suffix}", parent_event_id=parent,
        event_type="annual_total", status="ended",
        discharger_id=d.get("id"), discharger_name=" / ".join(names) or permit_row["label"] or None,
        npdes_permit=p0, waterbody_text=wtext, water_slugs=slugs, water_match=how,
        started_at=f"{year}-01-01", ended_at=f"{year}-12-31", time_precision="year",
        published_at=rep["published_at"], source_updated_at=rep["published_at"],
        material="combined sewage and stormwater (CSO)",
        volume_gal=gal, volume_text=vtext, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=None,
        source_url=rep["url"], raw=raw, parse_error=parse_error,
    )


def main(argv=None) -> int:
    disc = dischargers()
    errors: list[str] = []      # any failed part makes the run ok=False (records kept from the last good run)
    reports = {}
    for rep in REPORTS:
        if not rep["text"].exists():
            errors.append(f"missing report text {rep['text'].name}")
            continue
        reports[rep["year"]] = (rep, load_report(rep))
    if not reports:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(errors))
        print(f"{SOURCE_ID}: no report text", file=sys.stderr)
        return 1

    # outfall registry, reconciled with the newest report's outfall counts
    features, how, layer_error = fetch_layer()
    if layer_error:
        errors.append(layer_error)
    latest_rep, latest = reports[max(reports)]
    text = latest_rep["text"].read_text(errors="replace")
    oc = section(text, "Maine CSO Permittee Annual Number of CSO Outfalls\nPermittee", "Total Annual CSO Discharge")
    counts = {}
    for m in re.finditer(r"((?:(?:City-|PWD-)?ME ?\d{7}\s*(?:&|/)?\s*)+)((?:\d+\s+)*\d+)", re.sub(r"\s+", " ", oc)):
        permits = ["ME" + p for p in PERMIT_RE.findall(m.group(1))]
        counts[permits[0]] = {"permits": permits, "outfalls_latest": int(m.group(2).split()[-1])}
    outfalls = build_outfalls(features, how, counts)
    recon = []
    for p0, c in sorted(counts.items()):
        want = set(c["permits"]) | {a for p in c["permits"] for a in PERMIT_ALIASES.get(p, [])}
        n = sum(1 for o in outfalls if o["permit"] in want and o["status"] == "ACTIVE")
        if n != c["outfalls_latest"]:
            recon.append({"permits": c["permits"], "layer_active": n, f"report_{latest_rep['year']}": c["outfalls_latest"]})
    in_report = {a for c in counts.values() for p in c["permits"] for a in [p, *PERMIT_ALIASES.get(p, [])]}
    for permit in sorted({o["permit"] for o in outfalls if o["status"] == "ACTIVE"} - in_report):
        recon.append({"permits": [permit], "layer_active": sum(1 for o in outfalls if o["permit"] == permit and o["status"] == "ACTIVE"),
                      f"report_{latest_rep['year']}": 0, "note": "not a permittee in the report"})
    outfalls_path = BUILD_DIR / "me-cso-outfalls.json"
    prev_outfalls = read_json(outfalls_path, {}) or {}
    if layer_error and prev_outfalls.get("outfalls"):
        # keep the last good layer pull, marked as not refreshed
        prev_outfalls.update({"ok": False, "error": layer_error, "last_attempt_at": now_iso()})
        write_json(outfalls_path, prev_outfalls)
    else:
        write_json(outfalls_path, {
            "source_id": OUTFALL_SOURCE_ID, "source_url": LAYER_URL, "fetched_at": now_iso(), "fetched_via": how,
            "ok": layer_error is None, "error": layer_error,
            "count": len(outfalls), "active": sum(1 for o in outfalls if o["status"] == "ACTIVE"),
            "report_reconciliation": {"report": latest_rep["title"], "mismatches": recon},
            "note": "STATUS lags the DEP report by about two years; use report_reconciliation before treating "
                    "ACTIVE as current.",
            "outfalls": outfalls})

    # annual totals
    records: list[dict] = []
    problems = []
    rep25, t25 = reports.get(2025, (None, None))
    rep24, t24 = reports.get(2024, (None, None))
    first_2024: dict[str, dict] = {}
    if t24 and t25:
        # 2024 figures as first published (2024 report), for the permittee groups of the 2025 report.
        # The 2024 text merges neighbouring rows, so a parsed row is used only when it has the same
        # permit group and one value per year column; otherwise TRANSCRIBED_2024.
        for p0, grp in t25["rows"].items():
            row24 = t24["rows"].get(p0)
            gal = days = None
            note = None
            if row24 and row24["permits"] == grp["permits"]:
                gal = (row24["gal"] or {}).get(2024)
                days = (row24["days"] or {}).get(2024)
            tr = TRANSCRIBED_2024.get(p0)
            if tr and (gal is None or days is None):
                if gal is not None and gal != tr[0]:
                    problems.append(f"2024 report: parsed {gal} but transcribed {tr[0]} for {p0}")
                gal, days = tr
                note = "2024-report row interleaved in the text extraction; 2024 column transcribed by hand"
            if gal is None and days is None:
                problems.append(f"2024 report: no 2024 figure placed for {grp['permits']} ({grp['label']!r})")
                first_2024[p0] = make_record(
                    permit_row=grp, year=2024, gal=None, days=None, rep=rep24, outfalls=outfalls, disc=disc,
                    parse_error="2024 value not recoverable from the report text (blank or misaligned)",
                    note={"gal_raw": (row24 or {}).get("gal_raw"), "days_raw": (row24 or {}).get("days_raw")})
                continue
            first_2024[p0] = make_record(permit_row=grp, year=2024, gal=gal, days=days, rep=rep24,
                                         outfalls=outfalls, disc=disc, note=note)
    if t25:
        for p0, row in t25["rows"].items():
            gal_by, days_by = row["gal"], row["days"]
            if gal_by is None or days_by is None:
                # e.g. Rockland: 10 values for 15 year columns, blank cells not recoverable from text
                problems.append(f"2025 report: {row['permits']} has {len(row['gal_raw'] or [])} volume values for "
                                f"{len(t25['years'])} year columns; recorded 2025 as not placed")
                records.append(make_record(
                    permit_row=row, year=2025, gal=None, days=None, rep=rep25, outfalls=outfalls, disc=disc,
                    parse_error="row values do not line up with the year columns (blank cells in the PDF)",
                    note={"gal_raw": row["gal_raw"], "days_raw": row["days_raw"]}))
                first_2024.get(p0, {}).get("raw", {}).pop("confirmed_in", None)
                continue
            for year in sorted(y for y in t25["years"] if y >= FIRST_YEAR):
                gal, days = gal_by.get(year), days_by.get(year)
                if year == 2024 and p0 in first_2024:
                    prev = first_2024[p0]
                    if prev["volume_gal"] == gal and prev["raw"]["event_days"] == days:
                        prev["raw"]["confirmed_in"] = rep25["title"]
                        continue
                    records.append(make_record(
                        permit_row=row, year=year, gal=gal, days=days, rep=rep25, outfalls=outfalls, disc=disc,
                        key_suffix=":r2025", parent=prev["event_id"],
                        note=f"revised in the 2025 report (2024 report: {prev['volume_gal']} gal, "
                             f"{prev['raw']['event_days']} event-days)"))
                    continue
                records.append(make_record(permit_row=row, year=year, gal=gal, days=days, rep=rep25,
                                           outfalls=outfalls, disc=disc))
    records.extend(first_2024.values())
    records.sort(key=lambda r: (r["started_at"], r["npdes_permit"] or "", r["event_id"]), reverse=True)

    meta = {"registry_ids": ["me-dep-cso-status-report", "me-dep-mepdes-cso-outfalls"],
            "reports": [r["title"] for r, _ in reports.values()], "years": f"{FIRST_YEAR}-{max(reports)}",
            "outfalls_file": "data/build/me-cso-outfalls.json", "outfall_layer_via": how,
            "problems": problems, "cadence": "annual report each June-July; check monthly Jun-Aug"}
    meta["errors"] = errors
    path = write_events(SOURCE_ID, records, ok=not errors, error="; ".join(errors) or None, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} records, {len(outfalls)} outfalls ({how}); problems: {len(problems)} -> {path}")
    for p in problems:
        print("  ", p)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
