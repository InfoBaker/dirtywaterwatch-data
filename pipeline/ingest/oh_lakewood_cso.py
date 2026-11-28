"""City of Lakewood CSO alerts and status -> data/build/events/oh-lakewood-cso-map.json.

Public-record policy: downloaded source text is retained, including published names, contacts and addresses.
Structured event classification still uses the documented source fields. Requested removals apply at export.


Source (registry oh-lakewood-cso-map; 40 CFR 122.38, the Great Lakes CSO public notice rule)
  Lakewood's "CSO Alerts & Status" site, https://cso.lakewoodoh.gov/ (an ASP.NET page by Verdantas; 200 to GitHub's
  runner, probe 43941639288 of 2026-11-16; this machine cannot resolve the host). The page is rendered on the server:
  each monitored site (24 on 2026-11-16: the CSO outfalls CSO-002 to CSO-059 and the regulator meters "LEWS nnnn"
  and "RRES nnnn") has a card (a modal, id popup_<n>) with its name and a table of labelled rows. No data call behind
  the page was found: the Leaflet markers and the cards are both in the page. The cards come in four states, by the
  "Event status" or "Current status" row:
    Ongoing    "A combined sewer overflow (CSO) has begun ...": Event start, Discharge Location, Receiving Water,
               Public access areas affected, Data last updated (red marker);
    Completed  "... has ended ...": Event start, Event end, Total CSO event volume ("0.059 million gallons"),
               Discharge Location, Receiving Water, Public access areas affected, Data last updated (yellow: an
               event in the past 48 hours);
    not active "There are no overflow events in the past 48 hours": Last event ended, Current status "Overflow not
               active", Data last updated (green);
    Unknown    "The current status of this site is unknown ...": Data last updated (white: incomplete meter data).
  The Ongoing and Completed layouts were checked on the Internet Archive's captures of 2026-05-11 and 2026-06-16 (the
  live page showed only the last two states on 2026-11-16). The page says events are "based on a 6-hour window
  between activations". The page's footer names a city office with a telephone and an e-mail: never read or saved.

Records (a status snapshot turned into dated records, as oh_neorsd_cso does; the state keeps every event seen)
  - One cso record per site and start: source_record_id "<site slug>:<start, local YYYYMMDDTHHMM>". An Ongoing card
    opens it (status ongoing, ended_at null); the Completed card for the same start ends it (status ended,
    ended_at the card's end, minute) and gives the volume; a later card never erases an end it gave, and a changed
    end is kept in raw.end_revisions. While the site's card shows no state for that start (Unknown, or not active
    with a different end) the record keeps its end as last given; with none it is status unknown (end not confirmed).
  - When a site shows a newer start while an earlier record of the site still has no end, the earlier one ended at or
    before the newer start (raw.ended_at_precision bound, raw._end_basis says so). When a not-active card's "Last
    event ended" is at or after the start of a record with no end, that record ended at or before that time, the same
    way. Either bound is used only when it falls within 48 hours (BOUND_HOURS, the page's own window for a completed
    event) of the last read that showed the record ongoing: a bound months later (a meter outage, a feed outage)
    would colour the months between, so the record stays end not confirmed (status unknown) and raw.later_bound notes
    the bound. No other end is ever invented.
  - A not-active card's "Last event ended" that ends no record of the site (the first read, an outage of more than
    48 hours, or a bound not used above) is a record of its own: source_record_id "<site slug>:end:<end, local YYYYMMDDTHHMM>",
    started_at null (raw.start_note: the page gives no start), ended_at the time given, status ended. It carries no
    colour (no start); it is history.
  - Times: the page writes local wall-clock times with no zone; Lakewood is in Ohio, Eastern time: read as
    America/New_York (an hour that repeats when daylight time ends is read as its first occurrence; raw.time_zone).
    source_updated_at the card's "Data last updated" at the latest read that showed the event; reported_at and
    published_at null; fetched_at and raw._last_seen_in_source the last poll that showed it.
  - Volume: "Total CSO event volume" as written (volume_text); volume_gal from million gallons; estimate_flag
    unknown (the page does not say whether it is metered or modelled).
  - Place: permit OH0026018 (City of Lakewood; data/dischargers.json oh-lakewood-wwtp-oh0026018). A card named
    "CSO-nnn" is tied to the registry's outfall nnn of that permit only when exactly that number is an open CSO
    outfall with its own permitted-feature point (002, 052, 053, 055, 056, 057, 058, 059 on 2026-11-16): outfall_id
    and the registry's point (coord_source outfall_layer). "CSO-056A" and "CSO-056B" are not 056, and the LEWS and
    RRES meters are not registry outfalls: no outfall, no point (the page's own marker points are not used).
    A tie needs the receiving water known (the card's, or the page's other cards for the site) and refuses one that is
    not the registry row's water (raw.place_basis says
    which). waterbody_text is the card's "Receiving Water" as named; a start-less record (below) whose card gives
    none takes the water the page names for the same site on its other events (raw.water_basis); raw.discharge_location the card's street description
    (a house number in it is removed); raw.public_access_areas_affected as written ("Unknown").
  - advice_text null: the cards give no advice.

State: data/build/oh-lakewood-cso-state.json (every event seen; the archive). Do not delete it.
Failures: a failed request, a page with fewer than 10 cards or more than 3 fewer than the last read (truncated), or a card whose labels or status the reader does not know is a
  failed read for that card or page: a page with no readable card writes ok=False and keeps the previous records; one
  unknown card is named in the error, the rest are read, and health stays false (partial) until it reads.
History: the page shows only the latest event per site (48 hours for a completed one); it has no archive, so there is
  no --backfill. The hourly read is what makes the history.
Run from pipeline/: python -m ingest.oh_lakewood_cso [--file saved.html ... --out events.json] (saved pages are read as
  successive polls at the time of the run: use run() with each page's own read time to replay captures)
Cadence: hourly with the refresh (Ohio is live; the cards update every few minutes).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from ingest.oh_cso_pdf_notices import existing
from common import (BUILD_DIR, HEADERS, event, load_outfall_registry, now_iso, outfall_number, read_json, save_raw,
                    strip_house_numbers, write_events, write_json)
from common import error_detail, error_text

SOURCE_ID = "oh-lakewood-cso-map"
URL = "https://cso.lakewoodoh.gov/"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "OH0026018"
DISCHARGER = "City of Lakewood"
STATE_PATH = BUILD_DIR / "oh-lakewood-cso-state.json"
CREDIT = "City of Lakewood, CSO Alerts & Status"
MATERIAL = "combined sewage and stormwater"
LABELS = {"Event status": "event_status", "Event start": "start", "Event end": "end",
          "Total CSO event volume": "volume", "Discharge Location": "location", "Receiving Water": "water",
          "Public access areas affected": "public_access", "Last event ended": "last_ended",
          "Current status": "current_status", "Data last updated": "updated"}
EVENT_STATUSES = {"ongoing", "completed", "unknown"}
CURRENT_STATUSES = {"overflow not active"}
CARD = re.compile(r'<div class="modal fade" id="popup_(\d+)"')
TITLE = re.compile(r'<h4 class="card-title"[^>]*>(.*?)</h4>', re.S)
ROW = re.compile(r'<tr>\s*<td class="text-right font-weight-bold">(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', re.S)


class LayoutError(ValueError):
    """The page has no card this reader knows: a failed read, never "no overflows"."""


def clean(v: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", v or "")).split())


def local(v: str | None) -> datetime | None:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2}) ([AP])M", (v or "").strip(), re.I)
    if not m:
        return None
    mo, d, y, h, mi, ap = m.groups()
    if not 1 <= int(h) <= 12:
        return None
    try:
        return existing(datetime(int(y), int(mo), int(d), int(h) % 12 + (12 if ap.upper() == "P" else 0), int(mi),
                                 tzinfo=TZ))
    except ValueError:
        return None


def slug(site: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", site.lower()).strip("-")


def parse(page: str) -> tuple[list[dict], list[str]]:
    """(cards read, cards not read with the reason). Raises LayoutError when no card is found."""
    starts = [m.start() for m in CARD.finditer(page)]
    if not starts:
        raise LayoutError("no site card (popup_<n>) on the page")
    cards, unread = [], []
    for n, i in enumerate(starts):
        block = page[i:starts[n + 1] if n + 1 < len(starts) else len(page)]
        t = TITLE.search(block)
        site = clean(t.group(1)) if t else None
        if not site:
            unread.append(f"card {n + 1}: no site name")
            continue
        rows = {}
        bad = []
        for lab, val in ROW.findall(block):
            lab = clean(lab)
            if lab not in LABELS:
                bad.append(f"label '{lab[:40]}'")
                continue
            rows[LABELS[lab]] = clean(val)
        es, cs = (rows.get("event_status") or "").lower(), (rows.get("current_status") or "").lower()
        if es and es not in EVENT_STATUSES:
            bad.append(f"event status '{es[:30]}'")
        if cs and cs not in CURRENT_STATUSES:
            bad.append(f"current status '{cs[:30]}'")
        if not es and not cs:
            bad.append("no status row")
        for k in ("start", "end", "last_ended", "updated"):
            if rows.get(k) and local(rows[k]) is None:
                bad.append(f"{k} '{rows[k][:30]}' not read")
        if es in ("ongoing", "completed") and not rows.get("start"):
            bad.append(f"{es} with no start")
        if es == "completed" and not rows.get("end"):
            bad.append("completed with no end")
        if bad:
            unread.append(f"{site}: " + ", ".join(bad))
            continue
        cards.append({"site": site, "source_text": clean(page), **rows})
    if not cards:
        raise LayoutError("no card could be read: " + "; ".join(unread[:5]))
    return cards, unread


MIN_CARDS = 10      # 24 sites on 2026-11-16
DROP_ALLOWED = 3


def complete(parsed: list[tuple[list[dict], list[str]]], state_path: Path) -> None:
    """A page with far fewer cards than the last read (a truncated or partial page) is a failed read, never a
    smaller set of sites with nothing to report (review 2026-11-16 P1)."""
    prev = ((read_json(state_path, {}) or {}).get("last_poll") or {}).get("cards") or 0
    for cards, unread in parsed:
        n = len(cards) + len(unread)
        if n < MIN_CARDS or n < prev - DROP_ALLOWED:
            raise LayoutError(f"{n} site cards on the page (the last read had {prev}): the page looks truncated")
        prev = n


def iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


BOUND_HOURS = 48     # the page keeps a completed event 48 hours: a later bound than that is not used as an end


def _utc(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def bound_end(ev: dict, at: datetime, basis: str, now: str) -> int:
    """End an event with no end at `at` (it ended at or before then) when `at` is within BOUND_HOURS of the last poll
    that showed it ongoing; a later one is only noted (raw.later_bound): an end months after the last sighting would
    colour the months between, so the record stays end not confirmed instead. Returns 1 when the end was set."""
    seen = ev.get("running_seen_at")
    if seen and (at - _utc(seen)).total_seconds() <= BOUND_HOURS * 3600:
        ev.update(end=iso(at), end_basis=basis, running=False, end_bound_seen_at=now)
        return 1
    ev.update(running=False, later_bound={"at": iso(at), "basis": basis, "seen_at": now})
    return 0


def poll(state: dict, cards: list[dict], now: str) -> dict:
    """Open or update the state's events from one snapshot of the cards (module docstring); returns counts."""
    evs = state.setdefault("events", {})
    counts = {"opened": 0, "updated": 0, "seen": 0, "bounded": 0, "end_only": 0}
    for c in cards:
        site, es = c["site"], (c.get("event_status") or "").lower()
        upd = iso(local(c.get("updated")))
        mine = {k: v for k, v in evs.items() if v["site"] == site}
        if es in ("ongoing", "completed"):
            st = local(c["start"])
            key = f"{slug(site)}:{st.strftime('%Y%m%dT%H%M')}"
            cur = evs.get(key)
            if cur is None:
                cur = evs[key] = {"site": site, "start": iso(st), "first_seen_at": now, "end_revisions": []}
                counts["opened"] += 1
            else:
                counts["seen"] += 1
            if es == "completed":
                end = iso(local(c["end"]))
                if cur.get("end") and cur["end"] != end:
                    cur["end_revisions"].append({"end": cur["end"], "basis": cur.get("end_basis") or "published",
                                                 "replaced_at": now})
                    counts["updated"] += 1
                cur.update(end=end, end_basis="published", volume=c.get("volume"))
            cur.update(source_text=c.get("source_text"), running=es == "ongoing" and not cur.get("end"), last_seen_at=now, updated=upd,
                       location=c.get("location"), water=c.get("water"), public_access=c.get("public_access"),
                       last_state=es)
            if es == "ongoing":
                cur["running_seen_at"] = now
            for k2, ev2 in mine.items():         # an earlier event of this site left without an end
                if k2 != key and not ev2.get("end") and ev2.get("start") and ev2["start"] < iso(st):
                    counts["bounded"] += bound_end(ev2, st, "bound", now)
            continue
        for ev2 in mine.values():                # the site no longer shows an event: nothing is running
            ev2["running"] = False
        last = local(c.get("last_ended")) if c.get("last_ended") else None
        if last is None:
            continue
        hit = [v for v in mine.values() if v.get("end") == iso(last)]
        if hit:
            for v in hit:
                v["confirmed_at"] = now
            counts["seen"] += 1
            continue
        open_ = [v for v in mine.values() if not v.get("end") and v.get("start") and v["start"] <= iso(last)]
        if open_ and bound_end(max(open_, key=lambda v: v["start"]), last, "bound_last_ended", now):
            counts["bounded"] += 1
            continue                             # else the last end is a record of its own (below)
        key = f"{slug(site)}:end:{last.strftime('%Y%m%dT%H%M')}"
        if key not in evs:
            evs[key] = {"site": site, "start": None, "end": iso(last), "end_basis": "published", "first_seen_at": now,
                        "end_revisions": [], "running": False}
            counts["end_only"] += 1
        evs[key].update(last_seen_at=now, updated=upd)
    return counts


def outfall_points(rows: list[dict]) -> dict[str, dict]:
    """Lakewood's open CSO outfalls in the registry with their own point, by outfall number."""
    out = {}
    for r in rows:
        if r.get("npdes_permit") != PERMIT or r.get("outfall_kind") != "cso" or r.get("lat") is None:
            continue
        if str(r.get("outfall_status") or "").upper().startswith("CLS") or r.get("coords_from") != "permitted_feature":
            continue
        out[outfall_number(r.get("outfall"))] = r
    return out


def tie(site: str, points: dict[str, dict], water: str | None) -> dict | None:
    """The registry outfall a card names exactly ("CSO-052" is 052), unless the card's receiving water is not the
    registry row's water: then neither is trusted over the other and nothing is tied (raw.place_basis says so)."""
    m = re.fullmatch(r"CSO-(\d{3})", site.strip(), re.I)
    o = points.get(outfall_number(m.group(1))) if m else None
    # the water must be known (the card, or the page's other cards for the site) and the registry row's (review
    # 2026-11-16 P2)
    if o and (not water or not o.get("water_name") or water.strip().lower() != str(o["water_name"]).strip().lower()):
        return None
    return o


def _conflict(site: str, points: dict[str, dict], water: str | None) -> str | None:
    m = re.fullmatch(r"CSO-(\d{3})", site.strip(), re.I)
    o = points.get(outfall_number(m.group(1))) if m else None
    if o and not water:
        return (f"card {site} is outfall {o['outfall']} by number, but the page names no receiving water for the "
                "site to check it against: no outfall or point tied")
    if o and tie(site, points, water) is None:
        return (f"card {site} names {water} as its receiving water; the registry's outfall {o['outfall']} of {PERMIT} "
                f"is on {o['water_name']}: no outfall or point tied")
    return None


def to_record(key: str, ev: dict, points: dict[str, dict], site_water: dict[str, str] | None = None) -> dict:
    st = datetime.fromisoformat(ev["start"]) if ev.get("start") else None
    end = ev.get("end")
    basis = ev.get("end_basis")
    bound = basis in ("bound", "bound_last_ended")
    water = ev.get("water")
    water_from_site = None
    if not water and (site_water or {}).get(ev["site"]):
        water = water_from_site = site_water[ev["site"]]
    o = tie(ev["site"], points, water)
    status = "ongoing" if ev.get("running") else ("ended" if end else "unknown")
    raw = {"source_text": ev.get("source_text"), "site": ev["site"], "time_zone": TZ_NAME, "state": "OH", "_first_seen_at": ev["first_seen_at"],
           "_last_seen_in_source": ev["last_seen_at"], "last_card_state": ev.get("last_state"),
           "discharge_location": strip_house_numbers(ev["location"]) if ev.get("location") else None,
           "public_access_areas_affected": ev.get("public_access"),
           "time_note": "the page writes local times with no zone; Lakewood is in Ohio: read as America/New_York",
           "place_basis": (f"card {ev['site']} is registry outfall {o['outfall']} of {PERMIT}" if o else
                           _conflict(ev["site"], points, water) or
                           f"card {ev['site']} is not an outfall number in the registry for {PERMIT}: no outfall "
                           "or point tied")}
    if water_from_site:
        raw["water_basis"] = (f"this card gave no receiving water; the page names {water_from_site} for the same site "
                              "on its other events")
    if end:
        raw["ended_at_precision"] = "bound" if bound else "minute"
    if basis == "bound":
        raw["_end_basis"] = (f"the page later showed a newer event at {ev['site']}, starting {end}; this one ended at "
                             "or before then (its own end was not seen)")
    elif basis == "bound_last_ended":
        raw["_end_basis"] = (f"the page later gave {ev['site']}'s last event as ended at {end}; this event, last seen "
                             "without an end, ended at or before then")
    if st is None:
        raw["start_note"] = "the page gave only the end of the site's last event: no start is given"
    if ev.get("end_revisions"):
        raw["end_revisions"] = ev["end_revisions"]
    if status == "unknown":
        raw["end_note"] = "the page stopped showing this event without giving its end: end not confirmed"
        if ev.get("later_bound"):
            raw["later_bound"] = ev["later_bound"]
            raw["end_note"] += (f"; the page later showed {ev['later_bound']['at']} as a newer start or a last end, "
                                f"more than {BOUND_HOURS} hours after this event was last seen ongoing, so it is not "
                                "used as this event's end")
    vol = ev.get("volume")
    m = re.match(r"\s*(\d*\.?\d+)\s*million gallons", vol or "", re.I)
    gal = int(round(float(m.group(1)) * 1_000_000)) if m and not bound else None
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status=status,
        discharger_name=DISCHARGER, npdes_permit=PERMIT, outfall_id=o["outfall"] if o else None,
        outfall_name=ev["site"], waterbody_text=water,
        lat=o["lat"] if o else None, lon=o["lon"] if o else None, coord_source="outfall_layer" if o else None,
        started_at=st.isoformat() if st else None, ended_at=end, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=ev.get("updated"), fetched_at=ev["last_seen_at"],
        material=MATERIAL, volume_gal=gal, volume_text=vol if vol and not bound else None, estimate_flag="unknown",
        authority=CREDIT, advice_text=None, source_url=URL, raw=raw)


def run(cards: list[dict], now: str, state_path: Path, registry: list[dict] | None = None) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    counts = poll(state, cards, now)
    state["last_poll"] = {"at": now, "cards": len(cards), **counts}
    write_json(state_path, state)
    points = outfall_points(registry if registry is not None else load_outfall_registry())
    site_water = {}
    for ev in sorted(state["events"].values(), key=lambda v: v.get("last_seen_at") or ""):
        if ev.get("water"):
            site_water[ev["site"]] = ev["water"]          # the latest the page named for the site
    recs = [to_record(k, ev, points, site_water) for k, ev in state["events"].items()]
    recs.sort(key=lambda r: (r["started_at"] or r["ended_at"] or "", r["event_id"]), reverse=True)
    return recs, {"registry_ids": [SOURCE_ID], "url": URL, "poll": state["last_poll"], "credit": CREDIT,
                  "tied_outfalls": sorted(points)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", help="saved pages, read in order as successive polls (needs --out)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.file and not a.out:
        ap.error("--file needs --out")
    out = Path(a.out) if a.out else None
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    pages = []
    try:
        if a.file:
            pages = [Path(f).read_text(errors="replace") for f in a.file]
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(20, 90))
            r.raise_for_status()
            pages = [r.text]
        parsed = [parse(p) for p in pages]
        complete(parsed, state_path)
    except (requests.RequestException, LayoutError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {error_text(e)}", path=out)
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    recs, meta, unread = [], {}, []
    for cards, unread in parsed:
        if not a.file:
            save_raw(SOURCE_ID, json.dumps(cards), "json")        # the parsed cards only, never the page
        recs, meta = run(cards, now_iso(), state_path)
    if unread:
        meta["unread"] = unread
        write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, path=out,
                     error="cards not read: " + "; ".join(unread))
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; not read: {unread}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records from {meta['poll']['cards']} cards -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
