"""Arkansas Department of Health, Arkansas Swim Beach Program: the closed swim beaches it lists ->
data/build/events/ar-adh-swim-beach-status.json

Source
  https://healthy.arkansas.gov/programs-services/public-health-safety/marine-sanitation/arkansas-swim-beach-program/
  (registry: ar-adh-swim-beach-status). The Marine Sanitation Program's page: it reviews swim beach site plans,
  inspects, collects E. coli samples, and "monitors all sample results submitted to the Public Health Lab and advises
  the State Parks Commission, Environmental Health specialists, U.S. Forest Service, both the Little Rock and Vicksburg
  Corps of Engineer Districts, and all private swim beaches with the status of opening or closing beaches to
  swimmers". Its standard: when a sample's E. coli "exceeds 126 per 100 ml. daily samples shall immediately be
  collected". Under the heading "Closed Swim Beaches" it lists beaches by ADH's identifier and name ("SB112 - Jefferson
  Ridge West" on 2026-11-14, the only one). The list gives no date, no reason and no water. The program's rules are
  the Rules Pertaining to Outdoor Bathing Places (linked from the page).

Records (a standing list read as a snapshot)
  - One record per listed beach: event_type beach_closure (the beach category), status advisory_active while the page
    lists it, authority ADH, advice_text the page's words, raw.beach_id (ADH's SB number) and raw.beach_name.
  - started_at is the first read of the page that found it (time_precision poll; raw.start_basis: the closure began
    earlier, on a day ADH does not give); reported_at, published_at and source_updated_at stay null. Each read that
    lists it confirms it (raw._last_seen_in_source); the first read that no longer lists it ends it (advisory_lifted,
    ended_at that read, raw.ended_at_precision "poll"). A page whose heading cannot be found is ok=False: the records
    are kept and nothing ends.
  - Placement: ADH names the beach, not its water, and the page gives no point; USGS GNIS has no feature of the name.
    The record is listed and placed on no water (raw._placement named_water_only with no water text, raw.
    unplaced_reason), never placed by a guessed lake. A cited point per beach can be added to BEACH_POINTS.
  - The reason is not given: a closure can follow an E. coli result, high water or maintenance, so the record says
    "closed to swimmers" in ADH's heading's words and never states a cause.
  - Every line under the heading must be an SB item or a statement that none is closed; anything else (a maintenance
    notice, a changed layout) fails the run (ok=False) and ends nothing. A beach that leaves the list and comes back
    is a new episode and a new record (sbNNN-<first read>), so each closure keeps its own period.
Privacy: the list ends at the next heading of any kind; only the recognised SB numbers and names are kept in state and
data/raw (when they change), never the page's lines, so a contact block is never saved.

Run from pipeline/:  python -m ingest.ar_adh_swim_beaches [--file saved.html] [--at 2026-11-14T12:00:00Z]
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from pathlib import Path

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "ar-adh-swim-beach-status"
URL = ("https://healthy.arkansas.gov/programs-services/public-health-safety/marine-sanitation/"
       "arkansas-swim-beach-program/")
STATE_PATH = BUILD_DIR / "ar-adh-swim-beach-status-state.json"
AUTHORITY = "Arkansas Department of Health (Arkansas Swim Beach Program, closed swim beaches)"
ADVICE = ("Listed by the Arkansas Department of Health under “Closed Swim Beaches”; the Department advises "
          "beach managers “with the status of opening or closing beaches to swimmers”. No reason or date is "
          "given.")
START_BASIS = "the first read of ADH's page that listed this beach; the closure began earlier, on a day ADH does not give"
HEADING = re.compile(r"Closed\s+Swim\s+Beaches", re.I)
ITEM = re.compile(r"^\s*(SB\s*-?\s*\d+)\s*[\u2013\u2014-]+\s*([A-Za-z0-9][A-Za-z0-9 .,'&()/-]{0,80}?)\s*$", re.I)
EMPTY = re.compile(r"^\s*(none|no (swim )?beaches (are )?(currently )?closed\.?|there are no closed swim beaches\.?)\s*$",
                   re.I)
MARK = "\x00H "                    # a heading line: the list ends at the next one, whatever its words
# a cited point per beach, when one is found: {SB id: (lat, lon, basis)}
BEACH_POINTS: dict[str, tuple[float, float, str]] = {}


def list_lines(page: str) -> list[str]:
    """The lines under the 'Closed Swim Beaches' heading up to the next heading of any kind (or the end of the main
    content); ValueError without the heading. Nothing here is saved: read() keeps only recognised items."""
    s = re.sub(r"<(script|style|nav|header|footer)\b.*?</\1>", " ", page or "", flags=re.S | re.I)
    s = re.sub(r"</main\b.*", " ", s, flags=re.S | re.I)
    s = re.sub(r"<h\d\b[^>]*>", "\n" + MARK, s, flags=re.I)
    s = re.sub(r"<(?:br|p|li|tr|div|ul|ol|section|table|dl|dt|dd)\b[^>]*>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\u200b", " ").replace("\xa0", " ")
    lines = [ln for ln in (re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n")) if ln and ln != MARK.strip()]
    i = next((n for n, ln in enumerate(lines) if ln.startswith(MARK) and HEADING.fullmatch(ln[len(MARK):].strip(" :"))),
             None)
    if i is None:
        raise ValueError("the 'Closed Swim Beaches' heading was not found on the page")
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith(MARK):
            break
        out.append(ln)
    return out


def read(lines: list[str]) -> dict[str, str]:
    """{SB id: beach name}. Every line under the heading must be an SB item or a statement that none is closed;
    anything else (a maintenance notice, a changed layout, a contact block) is ValueError, so an unreadable list ends
    nothing and is never saved."""
    found = {}
    for ln in lines:
        m = ITEM.match(ln)
        if m:
            found[re.sub(r"[\s-]", "", m.group(1)).upper()] = m.group(2).strip()
        elif not EMPTY.match(ln):
            raise ValueError("a line under 'Closed Swim Beaches' is not a beach item; nothing is ended or saved")
    return found


def update(state: dict, found: dict[str, str], at: str) -> dict:
    """Each listing of a beach is its own episode: one that leaves the list ends at that read; one that comes back
    opens a new episode (a new record), so the earlier closure keeps its own period."""
    items = state.setdefault("items", {})
    for k, it in items.items():
        ep = it["episodes"][-1]
        if ep.get("left_at") is None and k not in found:
            ep["left_at"] = at
    for k, name in found.items():
        it = items.setdefault(k, {"episodes": []})
        if not it["episodes"] or it["episodes"][-1].get("left_at"):
            it["episodes"].append({"first_seen": at})
        it["episodes"][-1]["last_seen"] = at
        it["name"] = name
    state["last_poll"] = {"at": at, "listed": sorted(found)}
    return state


def records(state: dict) -> list[dict]:
    out = []
    for k, it in sorted(state.get("items", {}).items()):
        for n, ep in enumerate(it.get("episodes") or []):
            left = ep.get("left_at")
            rid = k.lower() if n == 0 else f"{k.lower()}-{re.sub(r'[^0-9T]', '', ep['first_seen'])[:13]}"
            raw = {"beach_id": k, "beach_name": it.get("name"), "first_seen_at": ep["first_seen"], "episode": n + 1,
                   "_last_seen_in_source": ep.get("last_seen"), "start_basis": START_BASIS, "state": "AR",
                   "time_zone": "America/Chicago", "advisory_noun": "Swim beach closure"}
            if left:
                raw.update(left_page_at=left, ended_at_precision="poll",
                           end_basis="the first read of the page that no longer listed it, not a reopening date ADH gives")
            pt = BEACH_POINTS.get(k)
            extra = {}
            if pt:
                # a cited point places the closure by its point (the beach's own place)
                extra = {"lat": pt[0], "lon": pt[1], "coord_source": "hand"}
                raw["point_basis"] = pt[2]
            else:
                raw.update(_placement="named_water_only",
                           unplaced_reason="ADH names the beach, not its water, and gives no point")
            out.append(event(source_id=SOURCE_ID, source_record_id=rid, event_type="beach_closure",
                             status="advisory_lifted" if left else "advisory_active", outfall_name=it.get("name"),
                             started_at=ep["first_seen"], ended_at=left, time_precision="poll", authority=AUTHORITY,
                             advice_text=ADVICE, source_url=URL, raw=raw, **extra))
    return out


def fetch() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    try:
        page = Path(argv[argv.index("--file") + 1]).read_text() if "--file" in argv else fetch()
        found = read(list_lines(page))
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    state = read_json(state_path, {}) or {}
    if "--file" not in argv and state.get("last_found") != found:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "closed": found}, indent=1).encode(), "json")
    state["last_found"] = found
    state = update(state, found, at)
    write_json(state_path, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "last_poll": state.get("last_poll"),
            "credit": "Arkansas Department of Health, Arkansas Swim Beach Program",
            "license": "No licence or terms stated on the page.",
            "timezone": "America/Chicago",
            "time_note": "The page gives no dates: a closure's start is the first read that listed it, its end the "
                         "first read that no longer did."}
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {sum(1 for r in recs if r['status'] == 'advisory_active')} listed; {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
