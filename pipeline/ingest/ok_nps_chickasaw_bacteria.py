"""National Park Service, Chickasaw National Recreation Area: E. coli results at its swimming places (Oklahoma).

Source
  https://www.nps.gov/chic/planyourvisit/bathing-beach-monitoring-program.htm (registry: ok-nps-chickasaw-bacteria),
  the park's Bathing Beach Monitoring Program page. U.S. government work. The page holds one table, "Status of Bacterial
  Levels for Beach Recreational Use": a row per sampling place (ten on 2026-11-14: Little Niagara, Bear Falls, Panther
  Falls, Black Sulphur Springs, Buckhorn Pavilion, Buckhorn Loop D, Point Day Use, 40 Ft Hole, Veterans Lake, Goddard
  Youth Camp), a column per weekly sample date ("8/6/26" to "8/27/26") and a "Geometric Mean" column; below it the
  park's key: "Values in red exceed threshold value" and "Threshold limit = weekly ≥ measurement 235 or 30 day
  geometric mean ≥126". The table states no unit. The park samples weekly in the summer swimming season and posts the
  results within 24 hours; when the five-week average or the geometric mean is above the action level it posts a sign
  at the swimming place ("the National Park Service advises against swimming in the stream until further notice") and
  removes it when both fall below. The page gives no posting or removal date.

Record rules (a sample is a sample: the accuracy-first rule of docs/generic-ingesters.md and ne_transforms)
  - Results are samples, not advisories. A result is a record only when it is at or above the park's own threshold, or
    when the park marks it in red: event_type beach_advisory, status unknown, raw._agency_label_only and
    raw._agency_label (the park's words), so the status build gives it the site's caution for 72 hours from the sample
    (data/rules.json unresolved.sample_caution), never the authority's advisory rule. sampled_at and started_at are the
    sample date (time_precision day, Central time): the date of the sample, never shown as a posting date.
  - A geometric mean at or above 126 (or in red) is one record per place for the table's latest sample date, the same
    way, its label saying the park posts a sign at that level under its procedure and that the page does not say a
    sign was posted.
  - A result below the threshold makes no record; every result read is counted in meta (places, dates, results,
    censored "<1" cells, the highest result and mean) with its qualifier kept, never read as zero.
  - A page whose table, dates or threshold line cannot be read writes ok=False and the previous records stay. A record
    whose result leaves the table keeps its record with raw._missing_from_source_since (its sample date is unchanged).
  - Placement: each place's water as the park describes it (Travertine Creek, Rock Creek, Veterans Lake, Lake of the
    Arbuckles), Murray County, with the USGS GNIS point of the named feature where GNIS has it (PLACES); never the
    outfall of Sulphur's plant, and never a cause: a high result is not a sewage report.
  - Privacy: only the table and the key are read; the page names no person. The raw save keeps the table and key only.

Run from pipeline/:  python -m ingest.ok_nps_chickasaw_bacteria [--file saved.html]
"""
from __future__ import annotations

import html
import re
import sys
from datetime import date
from pathlib import Path

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "ok-nps-chickasaw-bacteria"
URL = "https://www.nps.gov/chic/planyourvisit/bathing-beach-monitoring-program.htm"
AUTHORITY = "National Park Service, Chickasaw National Recreation Area (bathing beach monitoring)"
TZ = "America/Chicago"
GNIS = "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/{}"
POSTING = ("If the five week average and/or geometric mean is above the action level, the beach is posted with a sign "
           "notifying the public of high bacerial levels in the swimming area.")
# place as the table names it -> (water, GNIS feature or None). The park's own description: Little Niagara, Bear Falls
# and Panther Falls are on Travertine Creek; Travertine Creek flows into Rock Creek at Black Sulphur Springs, and the
# mixed water continues to 40' Hole; Veterans Lake is fed by Wilson Creek; the Buckhorn places, the Point and Goddard
# Youth Camp are on Lake of the Arbuckles. GNIS points read from The National Map's geonames service (Other Hydrographic
# Features), Murray County, 2026-11-14.
PLACES = {
    "Little Niagara": ("Travertine Creek", ("Little Niagara Falls", 34.508, -96.950, 1101938)),
    "Bear Falls": ("Travertine Creek", ("Bear Falls", 34.510, -96.954, 1101917)),
    "Panther Falls": ("Travertine Creek", ("Panther Falls", 34.503, -96.966, 1101944)),
    "Black Sulphur Springs": ("Rock Creek", ("Black Sulphur Springs", 34.506, -96.970, 1101921)),
    "40 Ft Hole": ("Rock Creek", None),
    "Veterans Lake": ("Veterans Lake", ("Veterans Lake", 34.490, -96.983, 1099249)),
    "Buckhorn Pavilion": ("Lake of the Arbuckles", None),
    "Buckhorn Loop D": ("Lake of the Arbuckles", None),
    "Point Day Use": ("Lake of the Arbuckles", None),
    "Goddard Youth Camp": ("Lake of the Arbuckles", None),
}
RED = re.compile(r"color\s*:\s*(?:red|#f00\b|#ff0000|rgb\(\s*255\s*,\s*0\s*,\s*0\s*\))", re.I)


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<(?!\d)[^>]*>", " ", fragment)).replace("\xa0", " ")).strip()


def read_value(cell: str) -> dict:
    """{text, value, qualifier, red}: '<1' is censored (qualifier '<', value 1), 'N/A' or blank no result."""
    t = text_of(cell)
    out = {"text": t, "value": None, "qualifier": None, "red": bool(RED.search(cell))}
    m = re.fullmatch(r"([<>]=?|≤|≥)?\s*(\d+(?:\.\d+)?)", t.replace(",", ""))
    if m:
        out["qualifier"], out["value"] = m.group(1), float(m.group(2))
    return out


def parse(page: str) -> dict:
    """{dates, rows: [{place, results: {date: value}, mean}], weekly, mean_limit, key, section}; ValueError if unread."""
    i = page.find("Status of Bacterial Levels")
    if i < 0:
        raise ValueError("no 'Status of Bacterial Levels' table on the page")
    j = page.find("</table>", i)
    k = page.find("</p>", page.find("Threshold limit", j)) if "Threshold limit" in page[j:j + 3000] else -1
    if j < 0 or k < 0:
        raise ValueError("the table or its threshold line cannot be found")
    table, key = page[i:j], text_of(page[j:k])
    m = re.search(r"weekly\s*(?:≥|>=)?\s*(?:measurement)?\s*(\d+).*?geometric mean\s*(?:≥|>=)\s*(\d+)", key, re.I | re.S)
    if not m:
        raise ValueError(f"unreadable threshold line: {key[:120]!r}")
    weekly, mean_limit = float(m.group(1)), float(m.group(2))
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    head = re.findall(r"<td[^>]*>(.*?)</td>", trs[0], re.S)
    dates = []
    for h in head[1:]:
        t = text_of(h)
        dm = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", t)
        if dm:
            y = int(dm.group(3))
            dates.append(date(y + 2000 if y < 100 else y, int(dm.group(1)), int(dm.group(2))).isoformat())
        elif "geometric mean" in t.lower():
            break
        else:
            raise ValueError(f"unreadable date column {t!r}")
    if not dates:
        raise ValueError("no sample dates in the table's first row")
    rows = []
    for tr in trs[1:]:
        tds = re.findall(r"(<td[^>]*>)(.*?)</td>", tr, re.S)
        place = text_of(tds[0][1]) if tds else ""
        if not place:
            continue
        vals = [read_value(open_tag + body) for open_tag, body in tds[1:]]
        results = {d: vals[n] for n, d in enumerate(dates) if n < len(vals) and vals[n]["text"]}
        mean = vals[len(dates)] if len(vals) > len(dates) and vals[len(dates)]["text"] else None
        rows.append({"place": place, "results": results, "mean": mean})
    if not rows:
        raise ValueError("no sampling place in the table")
    section = page[i:k + 4]
    return {"dates": dates, "rows": rows, "weekly": weekly, "mean_limit": mean_limit, "key": key, "section": section}


def _record(kind: str, place: str, sample: str, v: dict, limit: float, fetched: str, key: str) -> dict:
    water, gnis = PLACES.get(place, (None, None))
    q = (v["qualifier"] or "") + (f"{v['value']:g}" if v["value"] is not None else v["text"])
    if kind == "weekly":
        srid = f"{slug(place)}:{sample}"
        what = f"weekly result {q} in the sample of {sample}"
        label = (f"Values in red exceed threshold value (the park's key); threshold limit weekly {limit:g}"
                 if v["red"] else f"at or above the park's weekly threshold limit of {limit:g}")
        advice = (f"National Park Service, Chickasaw National Recreation Area: E. coli result {q} at {place} in the "
                  f"sample of {sample} ({label}; the table states no unit). A sample result, not a posted notice.")
    else:
        srid = f"{slug(place)}:mean:{sample}"
        what = f"geometric mean {q} with the sample of {sample}"
        label = (f"Values in red exceed threshold value (the park's key); threshold limit 30-day geometric mean {limit:g}"
                 if v["red"] else f"at or above the park's 30-day geometric mean threshold of {limit:g}")
        advice = (f"National Park Service, Chickasaw National Recreation Area: geometric mean {q} at {place} with the "
                  f"sample of {sample} ({label}). The park's procedure: \"{POSTING}\" The page does not say whether a "
                  "sign was posted, or when.")
    raw = {"place": place, "water": water, "county": "Murray County", "state": "OK", "result": v, "kind": kind,
           "threshold": limit, "threshold_line": key, "time_zone": TZ, "unit_note": "the table states no unit",
           "_agency_label_only": True, "_agency_label": label, "page_url": URL,
           "sample_note": "the sample date is the date of the sample, not the date a notice was posted or removed",
           "placement_hint": {"name": water or place, "county": "Murray County", "state": "OK",
                              "basis": "the park's description of the sampling place"}}
    lat = lon = None
    if gnis:
        lat, lon = gnis[1], gnis[2]
        raw["point_basis"] = f"{gnis[0]}: USGS GNIS feature {gnis[3]} (Other Hydrographic Features), Murray County"
        raw["point_url"] = GNIS.format(gnis[3])
    return event(source_id=SOURCE_ID, source_record_id=srid, event_type="beach_advisory", status="unknown",
                 waterbody_text=water or place, outfall_name=place, lat=lat, lon=lon,
                 coord_source="gnis" if gnis else None, coord_precision_m=300 if gnis else None,
                 started_at=sample, time_precision="day", sampled_at=sample, fetched_at=fetched, authority=AUTHORITY,
                 advice_text=advice, source_url=URL, raw=raw,
                 parse_error=None if water else f"a sampling place the crosswalk does not know: {place}")


def build(page: str, fetched: str, previous: list[dict]) -> tuple[list[dict], dict]:
    t = parse(page)
    recs: dict[str, dict] = {}
    n = {"results": 0, "censored": 0, "no_result": 0}
    top = (None, None, None)
    for row in t["rows"]:
        for d, v in row["results"].items():
            if v["value"] is None:
                n["no_result"] += 1
                continue
            n["results"] += 1
            n["censored"] += bool(v["qualifier"])
            if top[0] is None or v["value"] > top[0]:
                top = (v["value"], row["place"], d)
            if v["red"] or (not v["qualifier"] and v["value"] >= t["weekly"]):
                r = _record("weekly", row["place"], d, v, t["weekly"], fetched, t["key"])
                recs[r["source_record_id"]] = r
        mv = row["mean"]
        if mv and mv["value"] is not None and (mv["red"] or (not mv["qualifier"] and mv["value"] >= t["mean_limit"])):
            r = _record("mean", row["place"], t["dates"][-1], mv, t["mean_limit"], fetched, t["key"])
            recs[r["source_record_id"]] = r
    kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in recs:
            recs[sid]["raw"]["_first_seen_at"] = (p.get("raw") or {}).get("_first_seen_at") or p.get("fetched_at")
            continue
        p = dict(p)
        p["raw"] = {**(p.get("raw") or {}), "_missing_from_source_since":
                    (p.get("raw") or {}).get("_missing_from_source_since") or fetched}
        recs[sid] = p
        kept += 1
    for r in recs.values():
        r["raw"].setdefault("_first_seen_at", fetched)
    means = [row["mean"]["value"] for row in t["rows"] if row["mean"] and row["mean"]["value"] is not None]
    out = sorted(recs.values(), key=lambda r: (r["sampled_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "places": len(t["rows"]), "sample_dates": t["dates"], **n,
            "highest_result": {"value": top[0], "place": top[1], "sampled_at": top[2]},
            "highest_mean": max(means) if means else None, "threshold_weekly": t["weekly"],
            "threshold_mean": t["mean_limit"], "over_threshold": sum(1 for r in out if r["sampled_at"] in t["dates"]
                                                                   and not r["raw"].get("_missing_from_source_since")),
            "kept_from_previous": kept,
            "cadence": "weekly in the summer swimming season (the park's words); page read daily",
            "time_note": "sample dates are Central-time days; no posting or removal date is published"}
    return out, meta


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        if "--file" in argv:
            page = Path(argv[argv.index("--file") + 1]).read_text(errors="replace")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(30, 120))
            r.raise_for_status()
            page = r.text
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        recs, meta = build(page, fetched, prev)
        if "--file" not in argv:
            save_raw(SOURCE_ID, parse(page)["section"], "html")      # the table and its key only
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['places']} places, {len(meta['sample_dates'])} dates, {meta['results']} results "
          f"({meta['censored']} censored), {meta['over_threshold']} over the threshold, {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
