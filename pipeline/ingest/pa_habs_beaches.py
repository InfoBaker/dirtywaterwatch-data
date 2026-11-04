"""Pennsylvania cyanobacteria (HAB) response levels and Erie County beach advisories.

Writes two events files:

1. data/build/events/pa-doh-habs.json: PA Department of Health Harmful Algal Blooms layer
   https://services1.arcgis.com/Nifc7wlHaBPig3Q3/arcgis/rest/services/HABS2018_2021_FIXED/FeatureServer/0
   (behind the dashboard https://www.pa.gov/agencies/health/programs/environmental-health/habs-dashboard;
   no licence text). One row per water sample: Waterbody, Latitude/Longitude, dateobs (the sample
   day), newdateobs ("27OCT2026:09:17:00", local clock), TIME_OF_SAMPLE, toxin and cell counts and
   Response_Level: "No HAB issue detected", "Advisory (Yellow)", "Avoid Contact (Red)". The dashboard
   says the data are "NOT presented in real time" (updated Wednesdays and Fridays) and that the
   levels are based on risks of illness while swimming. Collector_ID (the sampler) is dropped.
   Current season only (samples since January 1 of this year). Records per waterbody: the samples of
   one sampling day count at the day's highest level; an advisory runs from the first day at Yellow
   or Red to the next day whose samples all read "No HAB issue detected" (hab_advisory,
   advisory_lifted, ended_at = that day's first sample) or is still standing (advisory_active,
   source_updated_at = the latest sample at Yellow or Red, which build/status.py ages out 14 days
   later). advice_text names the highest level reached. water_slugs: the openboatlaunch water named
   like the waterbody near its sample points (ingest/pa_waters.py, water_match "name").

2. data/build/events/pa-erie-beaches.json: Erie County Department of Health beach results
   (https://eriecountypa.gov/departments/health/services-and-programs/health-and-wellness/beach-water-testing-results/).
   The Google My Maps layer (KML export of mid 1B6FxSFxIGXX5z3R9mgjn3YHEck1ru5GM) gives each beach's
   point, "Current Status" and "Date updated", and links one Google Sheet per beach with every sample
   since 2015 (CSV export): Beach ID, Beach Name, Collection Date / Time, conditions, Result Value,
   Result Value Unit and "Advisory type" (blank, Advisory, Precautionary, Restriction). One record per
   row with an Advisory type: Advisory / Precautionary -> beach_advisory, Restriction -> beach_closure
   (the page: RED, "Swimming is not permitted at this time"); anything else -> unknown with a
   parse_error. started_at = the collection date (day precision; when the advisory was posted is not
   stated). The next sample row of that beach ends it (advisory_lifted, ended_at = its collection
   date, day precision; a following advisory row is its own record). The last row of a beach is
   advisory_active only while the map's Current Status still reads advisory or restriction; else it is
   lifted (as of the map's Date updated when that is within 21 days, else with no time). A next sample
   in a later season, or more than 21 days later, does not end an advisory. Values in the column that
   are not advisories ("None", "GM 114.6", "Closed for Season", repeated header rows) are skipped and
   counted; typos ("Adisory", "Prec Advisory") are read as Advisory with raw.reading_note. Hand-typed dates are read leniently ("6//30/2026"); an
   unreadable date on an advisory row gives a parse_error. water_slugs: Lake Erie (the Presque Isle
   and Freeport beaches are Lake Erie beaches; the sheets name no water), water_match "inferred".

Run from pipeline/: python -m ingest.pa_habs_beaches
Cadence: daily (the HAB layer is updated twice a week; beaches are sampled twice a week in season,
late May to Labor Day).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, read_json, save_raw, write_events
from ingest import pa_waters
from ingest.nh_vt_waters import norm

TZ = ZoneInfo("America/New_York")
HAB_ID = "pa-doh-habs"
HAB_LAYER = "https://services1.arcgis.com/Nifc7wlHaBPig3Q3/arcgis/rest/services/HABS2018_2021_FIXED/FeatureServer/0"
HAB_PAGE = "https://www.pa.gov/agencies/health/programs/environmental-health/habs-dashboard"
HAB_AUTHORITY = "Pennsylvania Department of Health HAB dashboard"
HAB_LEVELS = {"no hab issue detected": 0, "advisory (yellow)": 1, "avoid contact (red)": 2}
HAB_DROP = {"Collector_ID"}   # identifies the person who took the sample
HAB_NOTE = ("Response levels are the Department of Health's; its dashboard says thresholds are based on risks of "
            "illness associated with exposure while swimming, and the data are not real time (updated Wednesdays "
            "and Fridays).")

BEACH_ID = "pa-erie-beaches"
KML_URL = "https://www.google.com/maps/d/kml?mid=1B6FxSFxIGXX5z3R9mgjn3YHEck1ru5GM&forcekml=1"
BEACH_PAGE = "https://eriecountypa.gov/departments/health/services-and-programs/health-and-wellness/beach-water-testing-results/"
SHEET_CSV = "https://docs.google.com/spreadsheets/d/{id}/export?format=csv"
BEACH_AUTHORITY = "Erie County Department of Health beach monitoring"
ADVICE_YELLOW = ("A precautionary swimming advisory or a swimming advisory. Swimming is still permitted, but to reduce "
                 "the risk of illness, beach users are recommended to take precautions: avoid swallowing lake water; "
                 "parents should monitor children.")
ADVICE_RED = ("A precautionary restriction or a restriction. Swimming is not permitted at this time. Swimming can "
              "resume when water quality testing confirms that E. coli levels have dropped to acceptable limits.")
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}
MAX_GAP_DAYS = 21   # a later sample further away than this does not end an advisory


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-") or "x"


# ---------------------------------------------------------------- PA DOH HABs

def fetch_habs(sess: requests.Session, year: int) -> tuple[list[dict], bytes]:
    feats, offset, blobs = [], 0, []
    while True:
        r = sess.get(f"{HAB_LAYER}/query", params={
            "where": f"dateobs >= DATE '{year}-01-01'", "outFields": "*", "returnGeometry": "false",
            "orderByFields": "ObjectId", "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}, timeout=90)
        r.raise_for_status()
        js = r.json()
        if "features" not in js:
            raise ValueError(str(js)[:200])
        blobs.append(r.content)
        feats += [f.get("attributes") or {} for f in js["features"]]
        if not js.get("exceededTransferLimit") or not js["features"]:
            break
        offset += len(js["features"])
    return feats, b"\n".join(blobs)


def sample_time(a: dict) -> tuple[datetime | None, str]:
    s = (a.get("newdateobs") or "").strip()
    if s:
        try:
            return datetime.strptime(s.title(), "%d%b%Y:%H:%M:%S").replace(tzinfo=TZ), "minute"
        except ValueError:
            pass
    if a.get("dateobs") not in (None, ""):
        d = datetime.fromtimestamp(int(a["dateobs"]) / 1000, UTC).astimezone(TZ).date()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", (a.get("TIME_OF_SAMPLE") or "").strip())
        if m:
            return datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)), tzinfo=TZ), "minute"
        return datetime(d.year, d.month, d.day, tzinfo=TZ), "day"
    return None, "none"


def hab_episodes(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(episodes, rows not used) from one season's samples."""
    by_water, unused = defaultdict(list), []
    for a in rows:
        t, prec = sample_time(a)
        lvl = HAB_LEVELS.get((a.get("Response_Level") or "").strip().lower())
        name = (a.get("Waterbody") or "").strip()
        if t is None or lvl is None or not name:
            unused.append({**a, "_why": "no sample time" if t is None else "no waterbody" if not name
                           else f"unknown Response_Level {a.get('Response_Level')!r}"})
            continue
        by_water[norm(name)].append({"t": t, "prec": prec, "lvl": lvl, "a": a, "name": name})
    episodes = []
    for key, samples in by_water.items():
        samples.sort(key=lambda s: s["t"])
        days = defaultdict(list)
        for s in samples:
            days[s["t"].date()].append(s)
        cur = None
        for d in sorted(days):
            day = days[d]
            lvl = max(s["lvl"] for s in day)
            if lvl >= 1:
                if cur is None:
                    cur = {"water_key": key, "name": day[0]["name"], "samples": [], "days": [], "lifted_by": None}
                    episodes.append(cur)
                cur["samples"] += day
                cur["days"].append(d.isoformat())
            elif cur is not None:
                cur["lifted_by"] = day
                cur = None
        for ep in episodes:
            if ep["water_key"] == key:
                ep["all_points"] = [(s["a"].get("Longitude"), s["a"].get("Latitude")) for s in samples
                                    if s["a"].get("Longitude") is not None]
    return episodes, unused


def hab_record(ep: dict) -> dict:
    s0 = ep["samples"][0]
    top = max(ep["samples"], key=lambda s: (s["lvl"], s["t"]))
    last = max((s for s in ep["samples"] if s["lvl"] >= 1), key=lambda s: s["t"])
    pts = ep.get("all_points") or []
    centre = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None
    slugs, notes = pa_waters.match_waters(ep["name"], point=centre)
    lifted = ep["lifted_by"]
    end = min(s["t"] for s in lifted) if lifted else None
    level_text = top["a"].get("Response_Level")

    def lean(s):
        a = {k: v for k, v in s["a"].items() if k not in HAB_DROP}
        return {"sample_time": iso(s["t"]), **a}
    raw = {
        "samples": [lean(s) for s in ep["samples"]],
        "lifting_samples": [lean(s) for s in lifted] if lifted else None,
        "sampling_days": ep["days"], "highest_level": level_text,
        "episode_rule": ("The samples of one day count at the day's highest level; the advisory runs from the first day at "
                         "Yellow or Red to the next day whose samples all read 'No HAB issue detected'."),
        "water_placement": {"name": ep["name"], "notes": notes, "sample_centroid": centre},
        "level_note": HAB_NOTE,
    }
    return event(
        source_id=HAB_ID, source_record_id=f"{slugify(ep['name'])}-{s0['t']:%Y%m%d}",
        event_type="hab_advisory", status="advisory_lifted" if lifted else "advisory_active",
        waterbody_text=ep["name"], water_slugs=slugs, water_match="name" if slugs else "none",
        lat=last["a"].get("Latitude"), lon=last["a"].get("Longitude"),
        coord_source="source" if last["a"].get("Latitude") is not None else None,
        started_at=iso(s0["t"]), ended_at=iso(end), time_precision=s0["prec"],
        source_updated_at=iso(last["t"]), material="cyanobacteria (harmful algal bloom)",
        authority=HAB_AUTHORITY,
        advice_text=f"{level_text} (highest Department of Health response level in this period)",
        source_url=HAB_PAGE, raw=raw,
    )


def run_habs(sess: requests.Session) -> tuple[int, str]:
    year = datetime.now(TZ).year
    prev = read_json(EVENTS_DIR / f"{HAB_ID}.json", {}) or {}
    try:
        rows, content = fetch_habs(sess, year)
    except Exception as e:
        write_events(HAB_ID, [], ok=False, error=f"layer: {e}")
        return 1, f"{HAB_ID}: FAILED {e}"
    h = hashlib.sha256(content).hexdigest()
    if (prev.get("meta") or {}).get("raw_hash") != h:
        save_raw(HAB_ID, content, "json")
    episodes, unused = hab_episodes(rows)
    records = sorted((hab_record(ep) for ep in episodes), key=lambda r: r["started_at"] or "", reverse=True)
    ids = Counter(r["event_id"] for r in records)
    for r in records:
        if ids[r["event_id"]] > 1:
            r["event_id"] += "-" + hashlib.sha1(json.dumps(r["raw"]["sampling_days"]).encode()).hexdigest()[:6]
            r["source_record_id"] = r["event_id"].split(":", 1)[1]
    waters = {norm(a.get("Waterbody") or "") for a in rows if a.get("Waterbody")}
    meta = {"season": year, "samples": len(rows), "waterbodies_sampled": len(waters),
            "by_level": dict(Counter(a.get("Response_Level") for a in rows)),
            "latest_sample": max((iso(sample_time(a)[0]) for a in rows if sample_time(a)[0]), default=None),
            "unused_samples": [{k: v for k, v in a.items() if k not in HAB_DROP} for a in unused],
            "records_with_slug": sum(1 for r in records if r["water_slugs"]), "raw_hash": h, "level_note": HAB_NOTE,
            "layer": HAB_LAYER}
    path = write_events(HAB_ID, records, ok=True, meta=meta)
    c = Counter(r["status"] for r in records)
    return 0, (f"{HAB_ID}: {len(rows)} samples ({year}), {len(waters)} waterbodies; {len(records)} records {dict(c)}; "
               f"slug for {meta['records_with_slug']} -> {path}")


# ---------------------------------------------------------------- Erie County beaches

def parse_kml(text: str) -> list[dict]:
    """Beach placemarks of the 'Beach Advisories' folder: name, point, status, updated, sheet id."""
    root = ET.fromstring(text.encode() if isinstance(text, str) else text)
    out = []
    for folder in root.iter(f"{{{KML_NS['k']}}}Folder"):
        fname = (folder.findtext("k:name", default="", namespaces=KML_NS) or "").strip()
        if not re.search(r"beach", fname, re.I) or re.search(r"\bHABs?\b", fname):
            continue
        for pm in folder.findall("k:Placemark", KML_NS):
            data = {d.get("name"): (d.findtext("k:value", default="", namespaces=KML_NS) or "").strip()
                    for d in pm.iter(f"{{{KML_NS['k']}}}Data")}
            coords = (pm.findtext(".//k:coordinates", default="", namespaces=KML_NS) or "").strip().split(",")
            sheet = re.search(r"spreadsheets/d/([\w-]+)", " ".join(data.values()))
            out.append({"name": (pm.findtext("k:name", default="", namespaces=KML_NS) or "").strip(),
                        "lon": float(coords[0]) if len(coords) >= 2 else None,
                        "lat": float(coords[1]) if len(coords) >= 2 else None,
                        "current_status": data.get("Current Status") or data.get("Status"),
                        "description": data.get("Description"),
                        "date_updated": data.get("Date updated") or data.get("Date Updated"),
                        "sheet_id": sheet.group(1) if sheet else None})
    return out


def parse_day(s: str | None) -> date | None:
    s = re.sub(r"/+", "/", (s or "").strip())
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m or not 2000 <= int(m.group(3)) <= datetime.now(TZ).year + 1:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


# Values typed in the "Advisory type" column that are not an advisory: blank, "None", a geometric
# mean ("GM 114.6"), the season or a closed day ("Closed for Season", "Was not open to swimming
# this day"), a repeated header row.
NOT_ADVISORY = re.compile(r"^(none|n/?a|gm\b.*|closed for (the )?seas\w*|was not open.*|not open.*|advisory type)$", re.I)


def advisory_kind(v: str | None) -> tuple[str | None, str | None]:
    """(event_type or None when the value is not an advisory, note on a lenient reading)."""
    t = re.sub(r"\s+", " ", (v or "").strip().lower())
    if not t or NOT_ADVISORY.match(t):
        return None, None
    if t.startswith("restrict") or t in ("closed", "closure", "beach closed"):
        return "beach_closure", None
    if t in ("advisory", "precautionary", "precautionary advisory"):
        return "beach_advisory", None
    if re.fullmatch(r"prec\.? advisory|ad\w{0,2}isory|adv\w*", t):
        return "beach_advisory", f"Advisory type {v.strip()!r} read as Advisory"
    return "unknown", f"unrecognised Advisory type {v!r}"


def active_on_map(status: str | None) -> bool:
    return bool(re.search(r"advisory|restrict|swimming not permitted", status or "", re.I)) and \
        not re.search(r"closed for (the )?seas", status or "", re.I)


def beach_records(beach: dict, rows: list[dict], lake: list[str], sheet_url: str) -> tuple[list[dict], dict]:
    dated = []
    for k, r in enumerate(rows):
        d = parse_day(r.get("Collection Date"))
        dated.append((d, k, r))
    samples = sorted((x for x in dated if x[0]), key=lambda x: (x[0], x[1]))
    out, stats = [], Counter()
    updated = parse_day(beach.get("date_updated"))
    for d, k, r in dated:
        if (r.get("Collection Date") or "").strip() == "Collection Date":
            continue   # a header row repeated inside the sheet
        etype, note = advisory_kind(r.get("Advisory type"))
        if etype is None:
            if (r.get("Advisory type") or "").strip():
                stats["not_advisory_values"] += 1
            continue
        stats[etype] += 1
        nxt = next((x for x in samples if x[0] > d), None) if d else None
        if nxt and (nxt[0].year != d.year or (nxt[0] - d).days > MAX_GAP_DAYS):
            nxt = None   # the next sample is in a later season (or weeks later): the end is not known
        problems = [note] if etype == "unknown" and note else []
        if d is None:
            problems.append(f"unreadable Collection Date {r.get('Collection Date')!r}")
        if nxt:
            status, end = "advisory_lifted", nxt[0]
        elif d and active_on_map(beach.get("current_status")):
            status, end = "advisory_active", None
        else:
            status, end = ("advisory_lifted" if d else "unknown"), None
        bid = (r.get("Beach ID") or "").strip() or slugify(beach["name"])
        rid = f"{bid}-{d:%Y%m%d}" if d else f"{bid}-row{k + 2}"
        raw = {"row": r, "sheet_row": k + 2, "beach": {x: beach.get(x) for x in ("name", "current_status", "date_updated")},
               "start_basis": "the sample's collection date; when the advisory was posted is not stated",
               "end_basis": ("the next sample's collection date at this beach" if nxt else
                             f"no later sample within {MAX_GAP_DAYS} days in the same season; the map's Current Status "
                             + repr(beach.get("current_status"))),
               "reading_note": note if etype != "unknown" else None,
               "next_sample": {"date": nxt[0].isoformat(), "advisory_type": nxt[2].get("Advisory type") or None} if nxt else None,
               "water_basis": "Presque Isle State Park and Freeport beaches are Lake Erie beaches; the sheets name no water."}
        out.append(event(
            source_id=BEACH_ID, source_record_id=rid, event_type=etype, status=status,
            outfall_name=beach["name"], waterbody_text="Lake Erie", water_slugs=lake, water_match="inferred" if lake else "none",
            lat=beach.get("lat"), lon=beach.get("lon"), coord_source="source" if beach.get("lat") is not None else None,
            started_at=datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat() if d else None,
            ended_at=datetime(end.year, end.month, end.day, tzinfo=TZ).isoformat() if end else None,
            time_precision="day",
            source_updated_at=(datetime(updated.year, updated.month, updated.day, tzinfo=TZ).isoformat()
                               if updated and not nxt and d and 0 <= (updated - d).days <= MAX_GAP_DAYS else None),
            material=None,
            authority=BEACH_AUTHORITY, advice_text=ADVICE_RED if etype == "beach_closure" else ADVICE_YELLOW if etype == "beach_advisory" else None,
            source_url=sheet_url.replace("/export?format=csv", "/edit"), raw=raw,
            parse_error="; ".join(problems) if problems else None,
        ))
    return out, {"rows": len(rows), "dated_rows": len(samples), "advisory_rows": len(out), **stats,
                 "first": samples[0][0].isoformat() if samples else None, "last": samples[-1][0].isoformat() if samples else None}


def run_beaches(sess: requests.Session) -> tuple[int, str]:
    prev = read_json(EVENTS_DIR / f"{BEACH_ID}.json", {}) or {}
    prev_meta = prev.get("meta") or {}
    hashes = dict(prev_meta.get("raw_hashes") or {})
    try:
        r = sess.get(KML_URL, timeout=60)
        r.raise_for_status()
        beaches = parse_kml(r.text)
        if not beaches:
            raise ValueError("no beach placemarks in the KML")
    except Exception as e:
        write_events(BEACH_ID, [], ok=False, error=f"kml: {e}")
        return 1, f"{BEACH_ID}: FAILED {e}"
    h = hashlib.sha256(r.content).hexdigest()
    if hashes.get("kml") != h:
        save_raw(BEACH_ID, r.content, "kml")
        hashes["kml"] = h
    lake = [s for s in [pa_waters.named("Lake Erie", (-80.1, 42.15))] if s]
    prev_by_beach = defaultdict(list)
    for rec in prev.get("records", []):
        prev_by_beach[(rec.get("raw") or {}).get("beach", {}).get("name")].append(rec)
    records, per_beach, errors = [], {}, []
    for b in beaches:
        if not b.get("sheet_id"):
            per_beach[b["name"]] = {"error": "no results sheet linked", "current_status": b.get("current_status")}
            continue
        url = SHEET_CSV.format(id=b["sheet_id"])
        try:
            resp = sess.get(url, timeout=60)
            resp.raise_for_status()
            text = resp.content.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows or "Collection Date" not in rows[0]:
                raise ValueError("not the expected results sheet (no Collection Date column)")
        except Exception as e:
            errors.append(f"{b['name']}: {e}")
            records += prev_by_beach.get(b["name"], [])   # keep this beach's previous records
            per_beach[b["name"]] = {"error": str(e), "kept_previous": len(prev_by_beach.get(b["name"], [])),
                                    "current_status": b.get("current_status")}
            continue
        hh = hashlib.sha256(resp.content).hexdigest()
        if hashes.get(b["sheet_id"]) != hh:
            save_raw(BEACH_ID, resp.content, f"{slugify(b['name'])}.csv")
            hashes[b["sheet_id"]] = hh
        recs, st = beach_records(b, rows, lake, url)
        records += recs
        per_beach[b["name"]] = {**st, "current_status": b.get("current_status"), "date_updated": b.get("date_updated"),
                                "lat": b.get("lat"), "lon": b.get("lon"), "sheet_id": b["sheet_id"]}
        time.sleep(0.5)
    ids = Counter(x["event_id"] for x in records)
    seen = Counter()
    for x in records:
        if ids[x["event_id"]] > 1:
            seen[x["event_id"]] += 1
            if seen[x["event_id"]] > 1:
                x["event_id"] += f"-{seen[x['event_id']]}"
                x["source_record_id"] = x["event_id"].split(":", 1)[1]
    records.sort(key=lambda x: x["started_at"] or "", reverse=True)
    ok = len(errors) < len([b for b in beaches if b.get("sheet_id")])
    meta = {"beaches": per_beach, "sheet_errors": errors, "raw_hashes": hashes, "water_slugs": lake, "kml": KML_URL,
            "page": BEACH_PAGE}
    path = write_events(BEACH_ID, records, ok=ok, error="; ".join(errors) or None, meta=meta)
    c = Counter((x["event_type"], x["status"]) for x in records)
    return (0 if ok else 1), (f"{BEACH_ID}: {len(beaches)} beaches, {len(records)} records {dict(c)}"
                              f"{'; errors: ' + '; '.join(errors) if errors else ''} -> {path}")


def main() -> int:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    rc1, msg1 = run_habs(sess)
    print(msg1, file=sys.stderr if rc1 else sys.stdout)
    rc2, msg2 = run_beaches(sess)
    print(msg2, file=sys.stderr if rc2 else sys.stdout)
    return 1 if (rc1 and rc2) else 0


if __name__ == "__main__":
    sys.exit(main())
