"""Camden County MUA 'CSO Status' page -> data/build/events/nj-ccmua-cso-status.json.

Source
  https://www.ccmua.org/cso-status/ (registry row nj-ccmua-cso-status; research/nj/report.md §2.3),
  read through the WordPress REST API (pages/13694, content.rendered) and, when that fails, the page
  itself. A server-side code block on the page prints the status of one outfall: "The 32nd Street
  CSO permitted outfall 040A located at 32nd and Farragut Street into the Delaware River is [gate
  icon] CLOSED and discharges are unlikely to be occurring." A rich-text paragraph above it repeats
  the sentence with a fixed CLOSED; it is kept in raw (static_text) but the code block is what is
  read. The status carries no time: the page's modified date is an edit of the page, not of the
  status (kept in raw as page_modified_gmt). The website is the notification CCMUA's CSO permit
  NJ0026182 requires (Part IV.F.8). It covers 1 of about 30 CSO outfalls in the Camden area: Camden
  City's 22 and Gloucester City's 7 are not on it, and neither publishes a status.

What OPEN means
  The page does not say. Its CLOSED wording ("discharges are unlikely to be occurring") and the gate
  icon say it reports the position of the outfall's gate; OPEN is read as an overflow likely
  occurring: a gate-position status, not a measured or reported discharge (raw.status_basis). OPEN
  has not been seen (2026-11-02, 2026-11-03), so its wording is unknown: any status word in the
  block other than OPEN or CLOSED is "unreadable".

State machine (data/build/nj-ccmua-cso-status-state.json, the archive: do not delete it). Every
time is one of our polls (time_precision "poll"); the page gives none.
- open: the first poll that reads OPEN opens a cso event (ongoing): started_at = that poll's time
  (the gate opened at or before then; raw.started_after = the last poll that read CLOSED).
- continue: later OPEN polls (raw.last_open_at).
- close: the first poll that reads CLOSED ends it: ended_at = that poll's time (it closed at or
  before then; raw.ended_after = the last OPEN poll).
- reappear: OPEN after a close opens a new event.
- unreadable (the page answers but its block says neither OPEN nor CLOSED): no event; an open event
  becomes status unknown until the page is read again (OPEN continues it, CLOSED closes it). A fetch
  that fails changes nothing (write_events ok false keeps the previous records).
Every poll's reading is kept in state["readings"] as runs ({status, first, last, polls}), so what
the page said survives even when no event is written. Raw responses go to data/raw/nj-ccmua-cso-status/
when the status block or the page's modified date changed.

Run from pipeline/:  python -m ingest.nj_ccmua
Cadence: hourly with the refresh; a gate opening shorter than the gap between polls is missed.
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "nj-ccmua-cso-status"
PAGE_URL = "https://www.ccmua.org/cso-status/"
REST_URL = "https://www.ccmua.org/wp-json/wp/v2/pages/13694"
STATE_PATH = BUILD_DIR / "nj-ccmua-cso-status-state.json"
OUTFALLS = BUILD_DIR / "nj-cso-outfalls.json"
TZ = ZoneInfo("America/New_York")

PERMIT, OUTFALL = "NJ0026182", "040A"
DISCHARGER_ID = "nj-ccmua"
DISCHARGER_NAME = "Camden County Municipal Utilities Authority"
OUTFALL_NAME = "32nd Street CSO (32nd and Farragut Street)"
WATERBODY = "Delaware River"
AUTHORITY = "Camden County Municipal Utilities Authority, CSO Status page"
STATUS_BASIS = ("CCMUA's page shows the position of the gate on outfall 040A. CLOSED is worded \"discharges are "
                "unlikely to be occurring\"; OPEN is read here as an overflow likely occurring. A gate-position "
                "status, not a measured or reported discharge.")
TIME_BASIS = {
    "precision": "poll: the page gives no time; started_at and ended_at are our hourly polls",
    "started_at": "the first poll that read OPEN; the gate opened at or before it, after started_after",
    "ended_at": "the first poll that read CLOSED again; the gate closed at or before it, after ended_after",
}
COVERAGE = ("One outfall (040A) of about 30 CSO outfalls in the Camden area; Camden City's 22 and Gloucester "
            "City's 7 publish no status.")


# ---------------------------------------------------------------- parsing

def _text(fragment: str | None) -> str | None:
    if fragment is None:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*Press F5 to Refresh Page\s*$", "", t, flags=re.I).strip()
    return t or None


def parse_status(content: str) -> dict:
    """The status block of the page (div.post-entry): {status open|closed|unreadable, word, sentence,
    icon, static_text, block_found}."""
    m = re.search(r'<div[^>]*class="[^"]*\bpost-entry\b[^"]*"[^>]*>(.*?)</div>', content or "", re.S | re.I)
    block = m.group(1) if m else None
    word = None
    if block is not None:
        b = re.search(r"<b>\s*([^<]+?)\s*</b>", block, re.I)
        word = (b.group(1) if b else "").strip().upper() or None
        if word is None:
            w = re.search(r"\b(OPEN(?:ED)?|CLOSED)\b", _text(block) or "")
            word = w.group(1) if w else None
    status = {"OPEN": "open", "OPENED": "open", "CLOSED": "closed"}.get(word or "", "unreadable")
    icon = re.search(r'<img[^>]+src="([^"]+)"', block or "", re.I)
    static = re.search(r"<p>\s*(The 32nd Street CSO.*?)</p>", content or "", re.S | re.I)
    return {"status": status, "word": word, "sentence": _text(block), "icon": icon.group(1) if icon else None,
            "static_text": _text(static.group(1)) if static else None, "block_found": block is not None}


def fetch(sess: requests.Session) -> tuple[str, dict, bytes, str]:
    """(content html, page fields, response bytes, extension); REST first, the page as a fallback."""
    err = None
    try:
        r = sess.get(REST_URL, timeout=45)
        r.raise_for_status()
        js = r.json()
        content = ((js.get("content") or {}).get("rendered")) if isinstance(js, dict) else None
        if not content:
            raise ValueError("no content.rendered")
        return content, {"via": REST_URL, "page_modified_gmt": js.get("modified_gmt"), "link": js.get("link")}, r.content, "json"
    except (requests.RequestException, ValueError) as e:
        err = f"REST: {e}"
    r = sess.get(PAGE_URL, timeout=45)
    r.raise_for_status()
    return r.text, {"via": PAGE_URL, "page_modified_gmt": None, "rest_error": err}, r.content, "html"


# ---------------------------------------------------------------- state machine

def local(t: str) -> str:
    return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(TZ).isoformat(timespec="seconds")


def step(state: dict, reading: dict, now: str) -> dict:
    """One poll's reading into the state (module docstring). Returns this poll's counts."""
    evs = state.setdefault("events", {})
    runs = state.setdefault("readings", [])
    st = reading["status"]
    stats = Counter({st: 1})
    prev = runs[-1] if runs else None
    if prev and prev["status"] == st and prev.get("word") == reading.get("word"):
        prev["last"], prev["polls"] = now, prev["polls"] + 1
    else:
        runs.append({"status": st, "word": reading.get("word"), "first": now, "last": now, "polls": 1,
                     "sentence": reading.get("sentence")})
    last_closed = next((r["last"] for r in reversed(runs[:-1]) if r["status"] == "closed"), None)
    key = state.get("open")
    ev = evs.get(key) if key else None
    if st == "open":
        if ev is None:                                                   # open
            key = f"{OUTFALL}-{datetime.fromisoformat(local(now)):%Y%m%dT%H%M}"
            ev = evs[key] = {"state": "ongoing", "started_at": local(now), "started_at_utc": now,
                             "started_after": last_closed,
                             "sentence": reading.get("sentence"), "icon": reading.get("icon")}
            state["open"] = key
            stats["opened"] += 1
        elif ev["state"] != "ongoing":                                   # continue after an unreadable spell
            ev.setdefault("resumed", []).append({"at": now, "after": ev["state"]})
            ev["state"] = "ongoing"
        ev["last_open_at"] = now
    elif st == "closed":
        if ev is not None:                                               # close
            ev.update({"state": "ended", "ended_at": local(now), "ended_at_utc": now,
                       "ended_after": ev.get("last_open_at"), "closing_sentence": reading.get("sentence")})
            state.pop("open", None)
            stats["closed"] += 1
    elif ev is not None and ev["state"] == "ongoing":                    # unreadable
        ev["state"] = "unknown"
        ev["unreadable_since"] = now
    if ev is not None:
        ev["last_seen_at"] = now
    state["polls"] = state.get("polls", 0) + 1
    state["last_poll_at"] = now
    return dict(stats)


# ---------------------------------------------------------------- records

def place() -> dict:
    for o in (read_json(OUTFALLS, {}) or {}).get("outfalls", []):
        if o.get("npdes_permit") == PERMIT and str(o.get("outfall") or "").upper() == OUTFALL:
            return {"lat": o.get("lat"), "lon": o.get("lon"), "water_slugs": [o["water_slug"]] if o.get("water_slug") else [],
                    "water_match": o.get("water_match") or ("outfall_registry" if o.get("water_slug") else "none"),
                    "layer_outfall_id": o.get("outfall_id"), "layer_name": o.get("outfall_name")}
    return {"lat": None, "lon": None, "water_slugs": [], "water_match": "none"}


def to_record(key: str, ev: dict, where: dict, page: dict | None = None) -> dict:
    st = ev["state"]
    ended = ev.get("ended_at") if st == "ended" else None
    raw = {
        "sentence": ev.get("sentence"), "closing_sentence": ev.get("closing_sentence") if ended else None,
        "icon": ev.get("icon"), "status_basis": STATUS_BASIS, "time_basis": TIME_BASIS,
        "started_after": ev.get("started_after"), "last_open_at": ev.get("last_open_at"),
        "ended_after": ev.get("ended_after") if ended else None, "resumed": ev.get("resumed"),
        "unreadable_since": ev.get("unreadable_since") if st == "unknown" else None,
        "page_modified_gmt": (page or {}).get("page_modified_gmt"), "coverage": COVERAGE,
        "outfall_layer": {"id": where.get("layer_outfall_id"), "name": where.get("layer_name")},
    }
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso",
        status={"ongoing": "ongoing", "ended": "ended"}.get(st, "unknown"),
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER_NAME, npdes_permit=PERMIT,
        outfall_id=OUTFALL, outfall_name=OUTFALL_NAME, waterbody_text=WATERBODY,
        water_slugs=where.get("water_slugs") or [], water_match=where.get("water_match") or "none",
        lat=where.get("lat"), lon=where.get("lon"), coord_source="outfall_layer" if where.get("lat") is not None else None,
        started_at=ev.get("started_at"), ended_at=ended, time_precision="poll",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=ev.get("last_seen_at") or now_iso(),
        material=None, volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        source_url=PAGE_URL, raw=raw,
    )


def main() -> int:
    state = read_json(STATE_PATH, {}) or {}
    now = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        content, page, body, ext = fetch(sess)
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {e}")
        print(f"nj-ccmua-cso-status: FAILED {e}", file=sys.stderr)
        return 1
    reading = parse_status(content)
    h = hashlib.sha256(f"{reading['sentence']}|{reading['icon']}|{page.get('page_modified_gmt')}".encode()).hexdigest()
    if state.get("raw_hash") != h:
        save_raw(SOURCE_ID, body, ext)
        state["raw_hash"] = h
    stats = step(state, reading, now)
    state["page"] = page
    write_json(STATE_PATH, state)

    where = place()
    records = [to_record(k, ev, where, page) for k, ev in state["events"].items()]
    records.sort(key=lambda r: r["started_at"] or "", reverse=True)
    cur = state["readings"][-1]
    meta = {
        "current_status": cur["status"], "current_word": cur.get("word"), "current_sentence": cur.get("sentence"),
        "status_since": cur["first"], "static_text": reading.get("static_text"), "block_found": reading["block_found"],
        "via": page.get("via"), "page_modified_gmt": page.get("page_modified_gmt"), "rest_error": page.get("rest_error"),
        "poll": stats, "polls_total": state["polls"], "readings": state["readings"][-50:],
        "events_open": 1 if state.get("open") else 0, "status_basis": STATUS_BASIS, "time_basis": TIME_BASIS,
        "time_precision": "poll", "coverage": COVERAGE, "npdes_permit": PERMIT, "outfall_id": OUTFALL,
        "water_slugs": where.get("water_slugs"), "statewide": False,
    }
    err = None if reading["status"] != "unreadable" else (
        f"status not readable from the page (block found: {reading['block_found']}, word: {reading['word']!r})")
    path = write_events(SOURCE_ID, records, ok=True, error=err, meta=meta)
    print(f"nj-ccmua-cso-status: {cur['status']} ({cur.get('word')}) since {cur['first']}; {len(records)} events "
          f"({meta['events_open']} open); via {page.get('via')} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
