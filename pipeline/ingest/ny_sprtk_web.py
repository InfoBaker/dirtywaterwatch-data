"""DEC Sewage Pollution Right to Know page, "Recent NY-Alert Notifications" (New York)
-> data/build/events/ny-dec-sprtk-web.json

Source
  https://dec.ny.gov/environmental-protection/water/water-quality/sewage-pollution-right-to-know
  carries a server-rendered Drupal view (ul.c-view--sewage-notification) of the latest NY-Alert
  sewage notices: per row a headline, a <time datetime> in UTC (when DEC's view got the notice)
  and the full NY-Alert message ("New York Sewage Pollution Right to Know UPDATE Issued: ...
  Affects: New York - Orange - Warwick The Warwick (T) SD #1 NY0021890, NY0021890 is issuing this
  notification. Discharge location: ... Waterbody affected: ... Discharge date and time: ...").
  It is the near-live copy of what the DEC workbook (ingest/ny_sprtk.py) posts in batches months
  later. No API, no ids, no coordinates. Credit: "NYS DEC Sewage Pollution Right to Know page".

Quirks (research/ny/report.md 2.3)
  - A rolling window: 1-15 rows seen per capture. Every row seen is kept in
    data/build/ny-sprtk-web-state.json (keyed by view time + message hash), so the events file
    is the history polled so far. Polling every 15-30 minutes misses little.
  - No notification id: source_record_id is <facility id>-<view time>.
  - The UPDATE/ENDED word is missing on many Update and Close notices, so it is used only where
    present (ENDED -> ended); a notice continuing an ongoing chain stays ongoing; otherwise status
    is unknown. The message gives the duration without the workbook's "- Ongoing"/"- Ended" suffix.
  - Times in the message ("Issued", "Discharge date and time") are New York local clock time
    without an offset; the <time datetime> is UTC and has run one hour late for some notifiers.
    reported_at = Issued, published_at = the view time.
  - Dedupe against the workbook by facility + start (minute): a notice the workbook already holds
    (same chain, aired within 75 minutes) gets duplicate_of that workbook record; a notice newer
    than the workbook chain's latest gets parent_event_id = that record (it is the newer word); a
    notice older than the chain's latest is covered by the workbook (duplicate_of the latest).
    Web notices of one facility + address + start chain to each other by view time. Re-checked on
    every run, so web records fold into the workbook as DEC posts it.
  - A first notice's volume is the notifier's up-front estimate: estimate_flag "estimated".
  - Coordinates come from the matched workbook chain (the same notifier geocode) when there is
    one; otherwise none. Water slugs by receiving water name within New York, gated by that point.
  - The page sits behind a bot check for some clients; a 403 is retried with a browser user
    agent. A failed fetch writes ok:false and keeps the previous records.

Run (from pipeline/): python -m ingest.ny_sprtk_web
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta,
                    read_json, save_raw, strip_personal, write_events, write_json)
from ingest import ny_sprtk, ny_waters

SOURCE_ID = "ny-dec-sprtk-web"
PAGE_URL = "https://dec.ny.gov/environmental-protection/water/water-quality/sewage-pollution-right-to-know"
STATE_PATH = BUILD_DIR / "ny-sprtk-web-state.json"
WORKBOOK_EVENTS = EVENTS_DIR / f"{ny_sprtk.SOURCE_ID}.json"
TZ = ZoneInfo("America/New_York")
SAME_NOTICE = timedelta(minutes=75)   # the page's time has run an hour late for some notifiers

LABELS = [
    ("affects", "Affects"), ("discharge_location", "Discharge location"), ("location_details", "Location details"),
    ("waterbody", "Waterbody affected"), ("discharge_description", "Discharge description"),
    ("impacted_areas", "Potentially impacted public areas"), ("discharge_datetime", "Discharge date and time"),
    ("duration", "Discharge duration"), ("reason", "Discharge reason"),
    ("steps", "Steps taken to contain discharge"), ("volume", "Volume/rate of discharge"),
    ("treated_state", "Treated state of discharge"), ("additional", "Additional information"),
]
BOILERPLATE = [
    re.compile(r"\[?Disclaimer:.*$", re.S | re.I),
    re.compile(r"For more information on the Sewage Pollution Right to Know Act visit SPRTK\.?", re.I),
]


# ---------------------------------------------------------------- parsing

def clean(s: str | None) -> str | None:
    s = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())
    return s or None


def page_rows(page: str) -> list[dict]:
    """[{headline, view_time, text}] from the view's <li class="c-view__row"> items."""
    i = page.find("c-view--sewage-notification")
    if i < 0:
        raise ValueError("the sewage notification view is not on the page (layout changed or a bot check)")
    out = []
    for m in re.finditer(r'<li[^>]*class="[^"]*c-view__row[^"]*"[^>]*>(.*?)</li>', page[i:], re.S):
        body = m.group(1)
        head = re.search(r"<strong>(.*?)</strong>", body, re.S)
        t = re.search(r'<time[^>]*datetime="([^"]+)"', body)
        divs = re.findall(r"<div[^>]*>(.*?)</div>", body, re.S)
        text = clean(divs[-1]) if divs else None
        out.append({"headline": clean(head.group(1)) if head else None, "view_time": t.group(1) if t else None,
                    "text": text})
    return out


def parse_message(text: str) -> dict:
    """The fixed NY-Alert template -> fields (missing labels are None)."""
    t = " ".join((text or "").split())
    out = {"word": None, "issued": None, "issuer": None, "facility_id": None}
    m = re.search(r"Right to Know\s*(UPDATE|ENDED|INITIAL)?:?\s*Issued:\s*([\d-]+,?\s*[\d:]+)", t, re.I)
    if m:
        out["word"] = (m.group(1) or "").upper() or None
        out["issued"] = m.group(2)
    m = re.search(r"The (.+?) is issuing this notification\.", t)
    if m:
        out["issuer"] = m.group(1).strip()
        ids = re.findall(r"\b(NY\d{7}|NYS\d{6}|NYCDEPCSO)\b", out["issuer"])
        out["facility_id"] = ids[-1] if ids else None
    names = [lab for _k, lab in LABELS]
    for key, lab in LABELS:
        others = "|".join(re.escape(x) for x in names if x != lab)
        m = re.search(rf"{re.escape(lab)}:\s*(.*?)(?=\s*(?:{others}):|\s*\[Disclaimer|$)", t)
        out[key] = m.group(1).strip() if m else None
    if out["affects"]:
        # "New York - Orange - Warwick The Warwick (T) SD #1 ... is issuing" -> keep the place only
        out["affects"] = re.split(r"\s+The\s", out["affects"], maxsplit=1)[0].strip()
    for key in ("additional",):
        v = out.get(key) or ""
        for rx in BOILERPLATE:
            v = rx.sub("", v)
        out[key] = v.strip() or None
    return out


def local_dt(s: str | None) -> datetime | None:
    """'10-31-2026, 20:59:00' or '05-30-2025 00:00:00' (New York clock) -> aware datetime."""
    if not s:
        return None
    s = " ".join(s.replace(",", " ").split())
    for fmt in ("%m-%d-%Y %H:%M:%S", "%m-%d-%Y %H:%M", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    raise ValueError(f"time {s!r} not understood")


def duration_hours(text: str | None) -> float | None:
    """'70 Minutes', '16.7 Hours', '36 hours 45 min Hours', '20hrs 50min Hours' -> hours; else None."""
    t = (text or "").lower()
    h = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", t)
    mnt = re.search(r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)\b", t)
    if not h and not mnt:
        return None
    if h and mnt and h.start() < mnt.start():
        return float(h.group(1)) + float(mnt.group(1)) / 60
    if h:
        return float(h.group(1))
    return float(mnt.group(1)) / 60


def address_key(loc: str | None) -> str:
    """'50 State School Rd, Warwick, NY' -> '50 state school warwick' (street type and state dropped,
    close to the workbook's streetNumber + streetName + city)."""
    t = ny_sprtk.norm_text(re.sub(r",\s*NY\b.*$", "", loc or ""))
    t = re.sub(r"\b(rd|road|st|street|ave|avenue|blvd|dr|drive|ln|lane|pl|place|ct|hwy|pkwy|ter|way)\b", " ", t)
    return " ".join(t.split())


# ---------------------------------------------------------------- workbook index

def workbook_index() -> dict:
    """(facility id, start minute UTC) -> [workbook records in chain order], from ny-dec-sprtk.json."""
    data = read_json(WORKBOOK_EVENTS, {}) or {}
    idx: dict[tuple, list] = {}
    for r in data.get("records", []):
        fid = r.get("npdes_permit") or ny_sprtk.facility_of(ny_sprtk.canonical((r.get("raw") or {}).get("row") or {})[0])[0]
        if not fid or not r.get("started_at") or r.get("time_precision") != "minute":
            continue
        st = datetime.fromisoformat(r["started_at"]).astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
        idx.setdefault((fid, st), []).append(r)
    for lst in idx.values():
        lst.sort(key=lambda r: r.get("published_at") or "")
    return idx


# ---------------------------------------------------------------- records

def row_key(row: dict) -> str:
    h = hashlib.sha1((row.get("text") or "").encode()).hexdigest()[:10]
    return f"{row.get('view_time')}|{h}"


def build(state: dict, wb_idx: dict, ctx: dict) -> list[dict]:
    rows = sorted(state.get("rows", {}).values(), key=lambda r: r.get("view_time") or "")
    parsed = []
    for row in rows:
        m = parse_message(row.get("text") or "")
        problems = []
        try:
            issued = local_dt(m["issued"])
        except ValueError as e:
            issued, _ = None, problems.append(str(e))
        try:
            start = local_dt(m["discharge_datetime"])
        except ValueError as e:
            start, _ = None, problems.append(str(e))
        view = datetime.fromisoformat(row["view_time"].replace("Z", "+00:00")) if row.get("view_time") else None
        word = m["word"] or (re.match(r"\s*(UPDATE|ENDED)\b", row.get("headline") or "").group(1)
                             if re.match(r"\s*(UPDATE|ENDED)\b", row.get("headline") or "") else None)
        fid = m["facility_id"]
        name = ny_sprtk.clean_name(re.sub(r",?\s*(NY\d{7}|NYS\d{6}|NYCDEPCSO)\b.*$", "", m["issuer"] or "") or m["issuer"])
        parsed.append({"row": row, "m": m, "issued": issued, "start": start, "view": view, "word": word,
                       "fid": fid, "name": name, "addr": address_key(m["discharge_location"]),
                       "problems": problems})

    # web chains: facility + address + start, by view time
    chains: dict[str, list] = {}
    for p in parsed:
        k = f"{p['fid'] or ny_sprtk.norm_text(p['name'])}|{p['addr']}|{p['start'].astimezone(UTC):%Y-%m-%dT%H:%M}" \
            if p["start"] else f"single|{row_key(p['row'])}"
        chains.setdefault(k, []).append(p)

    records = []
    for k, lst in chains.items():
        prev_web = None
        for i, p in enumerate(lst):
            rec = to_record(p, i, lst, prev_web, wb_idx, ctx)
            records.append(rec)
            if not rec.get("duplicate_of"):
                prev_web = rec
    return records


def to_record(p: dict, i: int, chain: list, prev_web: dict | None, wb_idx: dict, ctx: dict) -> dict:
    m, row = p["m"], p["row"]
    fid, start, view = p["fid"], p["start"], p["view"]
    t_ref = view or p["issued"]
    rid = f"{fid or 'unknown'}-{(view or p['issued'] or datetime(1900, 1, 1, tzinfo=UTC)).astimezone(UTC):%Y%m%dT%H%M%SZ}"
    raw = {"headline": row.get("headline"), "view_time": row.get("view_time"), "text": row.get("text"),
           "first_seen_at": row.get("first_seen_at"), "last_seen_at": row.get("last_seen_at"),
           "parsed": {k: v for k, v in m.items() if v is not None},
           "_time_basis": "Issued and discharge times are New York local clock time in the message; view_time is UTC"}
    problems = list(p["problems"])
    parent, duplicate_of, parent_status = None, None, None
    wb_chain = wb_idx.get((fid, start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"))) if fid and start else None
    if wb_chain:
        same = [r for r in wb_chain if r.get("published_at") and t_ref and
                abs(datetime.fromisoformat(r["published_at"]) - t_ref) <= SAME_NOTICE]
        latest = wb_chain[-1]
        latest_t = datetime.fromisoformat(latest["published_at"]) if latest.get("published_at") else None
        if same:
            best = min(same, key=lambda r: abs(datetime.fromisoformat(r["published_at"]) - t_ref))
            duplicate_of = best["event_id"]
            raw["_dedupe"] = "the DEC workbook holds this notice (same facility and start, aired within 75 minutes)"
        elif latest_t and t_ref and t_ref < latest_t:
            duplicate_of = latest["event_id"]
            raw["_dedupe"] = "older than the workbook's latest notice in the same chain; the workbook carries the chain"
        else:
            parent, parent_status = latest["event_id"], latest.get("status")
            raw["_dedupe"] = "newer than the workbook's latest notice in the same chain (facility + start)"
    if not duplicate_of and prev_web is not None:
        parent, parent_status = prev_web["event_id"], prev_web.get("status")
    first_notice = parent is None and not duplicate_of

    if p["word"] == "ENDED":
        status = "ended"
    elif parent_status == "ongoing":
        status = "ongoing"
        raw["_status_note"] = ("carried from the chain's previous notice (ongoing): the page gives no ongoing/ended "
                               "marker and no ENDED word")
    else:
        status = "unknown"
        raw["_status_note"] = ("the page's UPDATE/ENDED word is unreliable and the duration carries no ongoing/ended "
                               "marker; status unknown unless ENDED")
    ended_at = None
    hrs = duration_hours(m.get("duration"))
    if status == "ended" and start and hrs is not None:
        ended_at = (start + timedelta(hours=hrs)).isoformat(timespec="seconds")
        raw["_ended_at_basis"] = f"computed: discharge start + reported duration ({m.get('duration')})"

    lat = lon = None
    coord_source = None
    if wb_chain:
        src = next((r for r in reversed(wb_chain) if r.get("lat") is not None), None)
        if src:
            lat, lon, coord_source = src["lat"], src["lon"], src.get("coord_source")
            raw["_coords"] = f"from the matching workbook chain ({src['event_id']})"

    f = {"facilityName": p["name"], "componentDescription": m.get("location_details"),
         "dischargeReason": m.get("reason"), "dischargeDescription": m.get("discharge_description"),
         "treatedState": m.get("treated_state"), "addressDescription": m.get("location_details")}
    permit = fid if fid and re.fullmatch(r"NY\d{7}", fid) else None
    etype, raw["_event_type_basis"] = ny_sprtk.classify(f, ctx["cso_permits"], permit)
    water = ny_sprtk.clean_water(m.get("waterbody"))
    town = (m.get("affects") or "").split(" - ")[-1].strip() or None
    outs = ny_sprtk.outfall_numbers(m.get("location_details"))
    pl = ny_sprtk.place(ctx, permit, outs, water, town, lat, lon, None)
    if pl["note"]:
        raw["_water"] = pl["note"]
    gal, vtext, est, vnote = ny_sprtk.volume_of(m.get("volume"), "New" if first_notice else "Update")
    if vnote:
        raw["_volume_note"] = vnote

    return event(
        source_id=SOURCE_ID, source_record_id=rid, parent_event_id=parent, duplicate_of=duplicate_of,
        event_type=etype, status=status,
        discharger_id=ctx["dischargers"].get(fid) or (f"ny-{ny_sprtk.slugify(p['name'])}" if p["name"] else None),
        discharger_name=p["name"], npdes_permit=permit,
        outfall_id=next(iter(outs)) if len(outs) == 1 else None, outfall_name=m.get("location_details"),
        waterbody_text=water, water_slugs=pl["slugs"], water_match=pl["match"],
        lat=lat, lon=lon, coord_source=coord_source,
        started_at=start.isoformat(timespec="seconds") if start else None, ended_at=ended_at,
        time_precision="minute" if start else None,
        reported_at=p["issued"].isoformat(timespec="seconds") if p["issued"] else None,
        published_at=view.astimezone(TZ).isoformat(timespec="seconds") if view else None,
        fetched_at=row.get("last_seen_at") or now_iso(),
        material=m.get("treated_state"), volume_gal=gal, volume_text=vtext, estimate_flag=est,
        authority=f"{p['name'] or 'Unnamed facility'} {ny_sprtk.AUTHORITY_SUFFIX}",
        advice_text=m.get("additional"), advice_window_hours=None, advice_window_basis=None,
        source_url=PAGE_URL, raw=raw, parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- main

def fetch(sess: requests.Session) -> str:
    r = sess.get(PAGE_URL, timeout=45)
    if r.status_code == 403:
        r = sess.get(PAGE_URL, timeout=45, headers=BROWSER_HEADERS)
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    state = read_json(STATE_PATH, {}) or {}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    now = now_iso()
    try:
        page = fetch(sess)
        rows = page_rows(page)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"ny-dec-sprtk-web: FAILED {e}", file=sys.stderr)
        return 1
    h = hashlib.sha256(page.encode()).hexdigest()
    # the page's own HTML changes with every Drupal build token; keep a copy when the rows change
    rows_hash = hashlib.sha256(repr(rows).encode()).hexdigest()
    if state.get("rows_hash") != rows_hash:
        save_raw(SOURCE_ID, page, "html")
        state["rows_hash"] = rows_hash
    state["page_hash"] = h
    store = state.setdefault("rows", {})
    new = 0
    for row in rows:
        k = row_key(row)
        if k not in store:
            store[k] = {**strip_personal(row), "first_seen_at": now}
            new += 1
        store[k]["last_seen_at"] = now
    state["last_poll_at"] = now
    state["polls"] = state.get("polls", 0) + 1
    write_json(STATE_PATH, state)

    dmap, cso = ny_sprtk.load_dischargers()
    ctx = {"echo": ny_sprtk.load_echo(), "dischargers": dmap, "cso_permits": cso, "place_cache": {}}
    records = build(state, workbook_index(), ctx)
    records.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    meta = {"rows_on_page": len(rows), "new_rows": new, "rows_kept": len(store), "polls_total": state["polls"],
            "duplicates_of_workbook": sum(1 for r in records if r.get("duplicate_of")),
            "newer_than_workbook": sum(1 for r in records if (r["raw"].get("_dedupe") or "").startswith("newer")),
            "water_match": {k: sum(1 for r in records if r["water_match"] == k) for k in ("outfall_registry", "name", "none")},
            "workbook_file": str(WORKBOOK_EVENTS.name)}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"ny-dec-sprtk-web: {len(rows)} rows on the page ({new} new), {len(records)} records kept; "
          f"{meta['duplicates_of_workbook']} already in the workbook, {meta['newer_than_workbook']} newer -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
