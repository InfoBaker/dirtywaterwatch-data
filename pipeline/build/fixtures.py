"""Fixture events from the wave-1 research traces (research/<area>/events.json).

    python -m build.fixtures            # writes data/build/events/fixture-<area>.json

The research agents traced real events by hand, each area in its own loose shape. This turns
every row into a schema record (docs/plan.md §3) so status and export can be exercised before
every ingester lands. Each file carries meta {"fixture": true}; build.status and export.build
label these events as fixtures; they are left out unless --fixtures (and, for export, DWW_ALLOW_FIXTURES=1).

Times in the traces are free text ("2026-08-03T~10:01 (computed ...)", "Oct  5 2026  8:50PM",
"2025-04-03 (discovered; time not published)"). The first date-time in the text is used for a
start and the latest for an end (the conservative reading for status); a date with no clock time
carries time_precision "day"; local times without an offset are America/New_York. A row whose
start cannot be read keeps started_at null (it then sets no status). Nothing is invented: the
original row is kept whole in `raw`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from common import EVENTS_DIR, ROOT, event, now_iso, parse_volume_gal, write_json

LOCAL = ZoneInfo("America/New_York")
AREAS = ["ma", "ct", "ri", "nh-vt", "me", "ny"]
RESEARCH = ROOT / "research"
NE = {"MA", "CT", "RI", "NH", "VT", "ME", "NY"}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
ISO_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ]~?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*([AaPp][Mm]))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?")
MON_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})"
                    r"(?:\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])?)?", re.I)
YEAR_RE = re.compile(r"^\s*(\d{4})\b(?!-)")

ADVISORY_TYPES = {"beach_advisory", "beach_closure", "hab_advisory", "shellfish_closure", "rain_advisory"}


def _mk(y, mo, d, hh, mm, ss, ampm, off):
    """(datetime, precision) from regex parts; None when the parts are not a real date."""
    try:
        if hh is None:
            return datetime(int(y), int(mo), int(d), tzinfo=LOCAL), "day"
        h = int(hh)
        if ampm:
            ap = ampm.lower()
            if ap == "pm" and h < 12:
                h += 12
            elif ap == "am" and h == 12:
                h = 0
        dt = datetime(int(y), int(mo), int(d), h, int(mm), int(ss or 0))
    except ValueError:
        return None
    if off == "Z":
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    elif off:
        o = off.replace(":", "")
        sign = 1 if o[0] == "+" else -1
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone(sign * timedelta(hours=int(o[1:3]), minutes=int(o[3:5]))))
    else:
        dt = dt.replace(tzinfo=LOCAL)
    return dt, "minute"


def find_times(text) -> list[tuple[datetime, str]]:
    """Every date or date-time in a free-text field, in order of appearance."""
    if text is None:
        return []
    s = str(text)
    found = []
    for m in ISO_RE.finditer(s):
        r = _mk(*m.groups())
        if r:
            found.append((m.start(), r))
    for m in MON_RE.finditer(s):
        mon, d, y, hh, mm, ap = m.groups()
        r = _mk(y, MONTHS[mon[:3].lower()], d, hh, mm, None, ap, None)
        if r:
            found.append((m.start(), r))
    if not found:
        m = YEAR_RE.match(s)
        if m:
            found.append((0, (datetime(int(m.group(1)), 1, 1, tzinfo=LOCAL), "year")))
    return [r for _, r in sorted(found, key=lambda x: x[0])]


def first_time(text):
    t = find_times(text)
    return t[0] if t else (None, None)


def last_time(text):
    """The latest time in the text (for an end: the conservative reading). A day-only end means
    the end of that day."""
    t = find_times(text)
    if not t:
        return None, None
    dt, prec = max(t, key=lambda x: x[0] + (timedelta(days=1) if x[1] == "day" else timedelta(0)))
    return dt, prec


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def map_type(text: str) -> str:
    t = (text or "").lower()
    if "annual" in t:
        return "annual_total"
    if "shellfish" in t:
        return "shellfish_closure"
    if "rainfall" in t and "beach" in t:
        return "rain_advisory"
    if "beach_closure" in t or "beach closure" in t:
        return "beach_closure"
    if "beach" in t:
        return "beach_advisory"
    if "hab" in t or "cyano" in t:
        return "hab_advisory"
    if "blend" in t or "partially_treated" in t or "partial" in t:
        return "blended"
    for k in ("bypass", "sso", "cso"):
        if t.startswith(k) or re.search(rf"\b{k}\b", t):
            return k
    return "unknown"


def map_estimate(v) -> str:
    if v is True:
        return "estimated"
    if v is False:
        return "measured"
    s = str(v or "").lower()
    if "estimat" in s or "model" in s or "guess" in s:
        return "estimated"
    if "actual" in s or "meter" in s or "measured" in s:
        return "measured"
    return "unknown"


def volume(v, units) -> tuple[int | None, str | None, str]:
    if v is None:
        return None, None, "unknown"
    u = str(units or "").lower()
    text = f"{v} {units}".strip() if units else str(v)
    if isinstance(v, (int, float)) and "million" not in u:
        return int(v), text, "unknown"
    if re.search(r"\bper\b", u) or "mgd" in str(v).lower():
        return None, text, "estimated"           # a rate, not a volume
    if isinstance(v, str) and "->" in v:         # a revision chain: the last figure is the latest
        if ";" in v:
            return None, text, "unknown"           # several chains (several facilities)
        v = v.rsplit("->", 1)[1]
    if "million" in u:
        m = re.search(r"(\d+(?:\.\d+)?)", str(v).replace(",", ""))
        if m and not re.search(r"\bmg\b", str(v).lower()):
            return int(float(m.group(1)) * 1_000_000), text, "unknown"
    gal, flag = parse_volume_gal(v)
    return gal, text, flag


PERMIT_RE = re.compile(r"\b([A-Z]{2}\d{7})\b")
WINDOW_RE = re.compile(r"(\d{2})\s*(?:hours|hrs|h)\b", re.I)


def load_dischargers() -> dict[str, dict]:
    by_permit = {}
    for a in AREAS:
        p = RESEARCH / a / "dischargers.json"
        if not p.exists():
            continue
        for d in json.loads(p.read_text()):
            for permit in PERMIT_RE.findall(str(d.get("npdes_permit") or "")):
                by_permit.setdefault(permit, d)
    return by_permit


def match_ids(r: dict) -> list[str]:
    """Ids a live ingester is likely to use for the same record, so status can drop the fixture
    once the real record exists (CT dashboard request ids, NY-Alert ids, MassDEP incident ids,
    VT incident numbers)."""
    ids = set()
    sri = r.get("source_record_id")
    if sri:
        ids.update(re.findall(r"\d{4,}", str(sri)))
    for pr in r.get("portal_records") or []:
        if isinstance(pr, dict) and pr.get("incidentId"):
            ids.add(pr["incidentId"])
    for u in (r.get("notice_urls") or []) + [r.get("notice_url") or ""]:
        ids.update(re.findall(r"[?&]FI=(\d+)", str(u)))
    return sorted(ids)


def convert(area: str, r: dict, dischargers: dict, fetched_default: str) -> dict:
    rid = r.get("event_id") or r.get("event_ref") or r.get("id")
    etype = map_type(r.get("event_type"))
    start_text = r.get("started_at") if r.get("started_at") is not None else r.get("date_start")
    if start_text is None and etype != "annual_total":
        start_text = r.get("date")
    end_text = r.get("ended_at") if "ended_at" in r else r.get("date_end")
    if etype == "annual_total":
        start_text = start_text or r.get("date")
    started, prec = first_time(start_text)
    ended, end_prec = last_time(end_text)
    if ended is not None and end_prec == "day":
        ended = datetime.combine(ended.date(), time(23, 59), tzinfo=LOCAL)
    if etype == "annual_total" and started is not None and prec == "year":
        ended = datetime(started.year, 12, 31, 23, 59, tzinfo=LOCAL)

    permits = PERMIT_RE.findall(str(r.get("npdes_permit") or ""))
    disc = dischargers.get(permits[0]) if permits else None
    src_status = str(r.get("source_status") or "").lower()
    now = datetime.now(LOCAL)
    if etype in ADVISORY_TYPES:
        if started is None:
            status = "unknown"
        elif ended is not None and ended <= now:
            status = "advisory_lifted"
        else:
            status = "advisory_active"
    elif etype in ("annual_total", "unknown"):
        status = "ended" if ended else "unknown"
    elif src_status.startswith("ongoing"):
        status = "ongoing"
    elif ended is not None:
        status = "ended"
    else:
        status = "unknown"

    advice = r.get("advice_text") or r.get("advice_text_quoted") or r.get("advisory_duration")
    window = None
    basis = None
    if advice and isinstance(advice, str):
        m = WINDOW_RE.search(advice)
        if m:
            window = int(m.group(1))
            basis = advice if len(advice) < 160 else advice[:157] + "..."
    gal, vtext, vflag = volume(r.get("volume"), r.get("units"))
    est = map_estimate(r.get("estimate_flag"))
    if est == "unknown":
        est = vflag
    slugs = r.get("water_slugs")
    if slugs is None:
        slugs = [r["water_slug"]] if r.get("water_slug") else []
    lat = lon = None
    coords = r.get("coordinates")
    if isinstance(coords, dict) and coords.get("lat") is not None:
        lat, lon = coords["lat"], coords["lon"]
        if lon is not None and lon > 0:   # NY DEC workbook swaps the sign/columns (noted in the trace)
            lon = -lon
    url = r.get("source_url") or r.get("notice_url") or (r.get("notice_urls") or [None])[0]
    reported, _ = first_time(r.get("reported_at"))
    published, _ = first_time(r.get("published_at"))
    updated, _ = last_time(r.get("source_updated_at"))
    fetched, _ = first_time(r.get("fetched_at") or r.get("checked"))
    raw = dict(r)
    raw["_match_ids"] = match_ids(r)
    raw["_fixture_from"] = f"research/{area}/events.json"
    return event(
        source_id=f"fixture-{area}", source_record_id=str(rid), event_type=etype, status=status,
        discharger_id=r.get("discharger_id") or (disc or {}).get("id"),
        discharger_name=r.get("discharger") if isinstance(r.get("discharger"), str) else None,
        npdes_permit=permits[0] if permits else None,
        outfall_id=None, outfall_name=r.get("outfall") or r.get("location_text"),
        waterbody_text=r.get("receiving_water") or r.get("waterbody"),
        water_slugs=list(slugs), water_match="inferred" if slugs else "none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=iso(started), ended_at=iso(ended), time_precision=prec,
        reported_at=iso(reported), published_at=iso(published), source_updated_at=iso(updated),
        fetched_at=iso(fetched) or fetched_default,
        material=r.get("material"), volume_gal=gal, volume_text=vtext, estimate_flag=est,
        authority=r.get("authority"), advice_text=advice if isinstance(advice, str) else None,
        advice_window_hours=window, advice_window_basis=basis,
        source_url=url, raw=raw,
        parse_error=None if (started or etype == "annual_total") else "start time not readable from the trace",
    )


def main() -> None:
    dischargers = load_dischargers()
    fetched = now_iso()
    for area in AREAS:
        p = RESEARCH / area / "events.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        rows = d["events"] if isinstance(d, dict) else d
        recs = [convert(area, r, dischargers, fetched) for r in rows]
        sid = f"fixture-{area}"
        write_json(EVENTS_DIR / f"{sid}.json", {
            "source_id": sid, "fetched_at": fetched, "ok": True, "error": None, "last_ok_at": fetched,
            "meta": {"fixture": True, "from": f"research/{area}/events.json",
                     "note": "hand-traced research events converted for testing; not a live feed"},
            "count": len(recs), "records": recs})
        print(f"{sid}: {len(recs)} records ({sum(1 for x in recs if x['started_at'])} dated)")


if __name__ == "__main__":
    main()
