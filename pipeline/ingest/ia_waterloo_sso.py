"""City of Waterloo, Iowa: SSO & Bypass Public Notification -> data/build/events/ia-waterloo-sso-notices.json.

Source
  https://www.ci.waterloo.ia.us/departments/waste_management/sso_and_bypass_public_notification.php (registry
  ia-waterloo-sso-notices): the Waste Management Services Department's page. The City writes that "under the Iowa
  Department of Natural Resources (IADNR) and Environmental Protection Agency (EPA) the city is required to notify the
  public of a Sanitary Sewer Overflow (SSO) or Bypass event", and lists them under "Recent SSO and Bypass Events": one
  paragraph per event, newest first ("October 1, 2026 at 5:52 AM, WMSD began Sanitary Sewer bypass pumping at a
  Sanitary Sewer Overflow located at ... The estimated volume of sewer discharged is 181,600 gallons; the duration of
  the event was 10 hours and 5 minutes. A sample was collected, warning sign #1 was placed ... Bypass pumping was the
  result of a wet weather event."). 17 notices on 2026-11-14 (16 from 2026, one from October 2025). The page names no
  receiving water and gives no point; the City's report forms sit in a linked folder that is not read.

Records (one per notice; all are sewage from the City's collection system)
  - event_type sso (a sanitary sewer overflow, or bypass pumping at one, from the collection system: lift stations,
    manholes, mains); "(permitted overflow)" and the cause sentence are kept in raw.
  - started_at the notice's date and time in Central time (minute precision) when the notice says "WMSD began ...".
    "WMSD was notified of ..." is the time the City learned of it: reported_at, started_at left empty (the start is not
    stated; raw.start_basis says so). ended_at: "The overflow was stopped at 12:00PM" when given, else, from a real
    start only, the start plus the stated duration ("10 hours and 5 minutes", "7.75 hours", "one hour", "two hours, 30
    minutes"), raw.ended_at_precision minute and raw.end_basis; a duration after a notification time makes no end
    (raw.duration_minutes_as_stated, raw.end_note); an unknown duration leaves no end (status unknown).
  - Volume: "The estimated volume of sewer discharged is N gallons" (estimate_flag estimated); unknown is null.
  - Place: no water and no point: waterbody_text none, placed on no water, listed with Black Hawk County and the City;
    the notice's location (a street, an intersection, a lift station) is kept in raw.location after the house-number
    scrub. Never geocoded, never put at the plant.
  - Identity: source_record_id the notice's local date and time (to the minute) and its saved location
    (minute~location, assign_ids), never numbered in page order; earlier ids are reserved, and a record saved with the
    bare minute keeps it while its minute and location match. A notice that leaves the page
    keeps its record (raw._unlisted_since); a paragraph the reader cannot read is an "unknown" record with
    parse_error, never dropped.
  Privacy: only the list of notices is read (the page's contact block is not); every street address's house number is
  removed before anything is saved (common.strip_house_numbers); the raw save is the scrubbed list, only when it changes.

Run from pipeline/: python -m ingest.ia_waterloo_sso [--file saved.html] [--at ISO]
Cadence: hourly with the refresh (the City posts each notice after the event).
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, end_after, event, now_iso, read_json, save_raw, scrub_text, \
    strip_house_numbers, write_events
from common import error_detail
from ingest.ia_id_privacy import home_place
from ingest.ia_id_privacy import scrub as strict_scrub

SOURCE_ID = "ia-waterloo-sso-notices"
URL = "https://www.ci.waterloo.ia.us/departments/waste_management/sso_and_bypass_public_notification.php"
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
AUTHORITY = "City of Waterloo Waste Management Services (SSO and bypass public notification)"
OPERATOR = "City of Waterloo"
OPERATOR_ID = "ia-waterloo"   # the operator row holding IA0042650 (data/dischargers.json)
PERMIT = "IA0042650"          # CITY OF WATERLOO (EPA ICIS-NPDES; research/ia/federal-seed.json)
START = re.compile(r"Recent SSO and Bypass Events", re.I)
END = re.compile(r"Listing of SSO & Bypass Public Notification Report Forms|Terms:", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
LEAD = re.compile(rf"^(?P<mon>{MONTHS})\s+(?P<day>\d{{1,2}}),\s*(?P<year>\d{{4}}),?\s*at\s*(?P<h>\d{{1,2}}):(?P<m>\d{{2}})"
                  rf"\s*(?P<ap>[AP])\.?\s*M\.?(?:\s*[AP]\.?M\.?)?\s*,?\s*", re.I)
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1}


def notices(page: str) -> list[str]:
    """The list's paragraphs; ValueError when the list's heading or its end is not on the page."""
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", page or "", flags=re.S | re.I)
    s = re.sub(r"<(?:br|p|li|h\d|tr|div)\b[^>]*>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").replace("​", " ")
    s = "\n".join(x for x in (re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")) if x)
    a = START.search(s)
    b = END.search(s, a.end()) if a else None
    if not a or not b:
        raise ValueError("the list of SSO and bypass events was not found on the page")
    body = s[a.end():b.start()].lstrip(": \n")
    # one notice per paragraph; a paragraph that does not start with a date is read (and kept as unreadable), never
    # folded into the notice before it
    return [re.sub(r"\s+", " ", p).strip() for p in body.split("\n") if p.strip(" :")]


def _num(s: str) -> float | None:
    s = s.strip().lower()
    if s in NUM_WORDS:
        return float(NUM_WORDS[s])
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def duration(text: str) -> timedelta | None:
    """The stated duration ("the duration of the event was 10 hours and 5 minutes"), None when unknown or absent."""
    m = re.search(r"duration of the (?:event|overflow) (?:was|is) ((?:[^.;]|\.(?=\d))+)", text, re.I)
    if not m or re.search(r"unknown", m.group(1), re.I):
        return None
    d = m.group(1)
    h = re.search(r"([\w.,]+)\s+hours?", d, re.I)
    mi = re.search(r"([\w.,]+)\s+minutes?", d, re.I)
    hv = _num(h.group(1)) if h else None
    mv = _num(mi.group(1)) if mi else None
    if hv is None and mv is None:
        return None
    return timedelta(hours=hv or 0, minutes=mv or 0)


def volume(text: str) -> tuple[int | None, str]:
    m = re.search(r"volume of sew(?:er|age) discharged (?:is|was) ([\d,]+)\s*gallons", text, re.I)
    if m:
        return int(m.group(1).replace(",", "")), f"{m.group(1)} gallons (estimated)"
    return None, "unknown"


def location(text: str) -> str | None:
    m = re.search(r"\b(?:located at|at)\s+(?:a Sanitary Sewer Overflow (?:located )?at\s+)?(.+?)(?:\.\s+The\b|\.\s*$|\.\s+A\b)",
                  text, re.I)
    if not m:
        return None
    loc = re.sub(r"^(?:a\s+)?Sanitary Sewer Overflow\s+(?:located\s+)?at\s+", "", m.group(1), flags=re.I)
    return strip_house_numbers(scrub_text(loc)).strip(" ,") or None


def slug(s: str) -> str:
    s = (s or "").replace("[house number removed]", " ")
    # Stable historical identity only; the record keeps the full source location.
    s = re.sub(r"(?<![A-Za-z0-9])\d{1,6}[A-Za-z]?\s+(?=[A-Za-z])", "", s)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def read(para: str) -> dict:
    """The notice's fields; ValueError when its date and time cannot be read."""
    text = strip_house_numbers(scrub_text(para))
    m = LEAD.match(text)
    if not m:
        raise ValueError("no date and time at the start of the notice")
    h = int(m.group("h")) % 12 + (12 if m.group("ap").upper() == "P" else 0)
    mon = MONTHS.split("|").index(m.group("mon").capitalize()) + 1
    start = datetime(int(m.group("year")), mon, int(m.group("day")), h, int(m.group("m")), tzinfo=TZ)
    rest = text[m.end():]
    notified = bool(re.match(r"WMSD was notified", rest, re.I))
    loc = location(rest)
    stop = re.search(r"(?:overflow|bypass(?:ing)?|event) was stopped at\s*(\d{1,2}):(\d{2})\s*([AP])\.?M", rest, re.I)
    end, end_basis, end_note = None, None, None
    d = duration(rest)
    if stop:
        eh = int(stop.group(1)) % 12 + (12 if stop.group(3).upper() == "P" else 0)
        end = start.replace(hour=eh, minute=int(stop.group(2)))
        if end < start:
            if notified:
                # a stop time before the time the City was notified, with no date: the day is not stated, so no end
                # is made from it (Astra 2026-11-15 P2-2)
                end, end_note = None, f"stopped at {stop.group(0).split(' at ')[-1]} (as written; its day is not stated)"
            else:
                end = (end + timedelta(days=1)).replace(tzinfo=TZ)      # the next calendar day, its own offset
        if end is not None:
            end_basis = "the time the notice says the overflow was stopped"
    elif d is not None and not notified:
        # elapsed time (in UTC), so a duration across a clock change ends at the right local time; only from a real
        # start: "was notified" is not when the overflow began, so its duration makes no end (Astra 2026-11-15 P2-2)
        end, end_basis = end_after(start, d, "minute")[0], "the notice's start plus the duration it states"
    gal, vtext = volume(rest)
    cause = re.search(r"(?:was|were) the result of ([^.]+)", rest, re.I)
    return {"start": start, "notified": notified, "location": loc, "end": end, "end_basis": end_basis,
            "end_note": end_note, "duration_minutes": round(d.total_seconds() / 60) if d is not None else None,
            "volume_gal": gal, "volume_text": vtext, "cause": cause.group(1).strip() if cause else None,
            "permitted_overflow": bool(re.search(r"permitted overflow", rest, re.I)),
            "bypass_pumping": bool(re.search(r"bypass pumping", rest, re.I)), "text": text}


def id_location(f: dict) -> str:
    """The location as it is saved (a private home's dropped, text that may name a person withheld): the id never
    carries what the record does not (lessons 6 and 7)."""
    if home_place(f.get("text"), f.get("location")):
        return ""
    loc = strict_scrub(f.get("location"))
    return "" if not loc or loc.startswith("[withheld") else slug(loc)


def assign_ids(parsed: list[dict], previous: list[dict]) -> list[str]:
    """Each notice's source_record_id, whatever the page's order or which notices are read together: the start minute
    and the location (minute~location). An earlier record with the same minute and location keeps its id (records
    saved before with the bare minute included); every other earlier id is reserved, so a different notice at the same
    minute on a later run never takes it: a correction is never inferred from the minute alone (Astra 2026-11-15 P1-4)."""
    prev = {}
    for p in previous:
        sid = p.get("source_record_id") or ""
        if sid and not sid.startswith("unread-"):
            raw = p.get("raw") or {}
            prev[sid] = id_location({"text": raw.get("notice"), "location": raw.get("location")})
    bases = [f["start"].strftime("%Y-%m-%dT%H%M") for f in parsed]
    locs = [id_location(f) for f in parsed]
    ids: list[str | None] = [None] * len(parsed)
    taken = set(prev)                                    # every earlier id is reserved
    reused = set()
    order = sorted(range(len(parsed)), key=lambda i: (bases[i], locs[i], parsed[i]["text"]))
    # first, an earlier record with the same minute and location keeps its id
    for i in order:
        for sid, ploc in sorted(prev.items()):
            if sid.split("~")[0] == bases[i] and ploc == locs[i] and sid not in reused:
                ids[i] = sid
                reused.add(sid)
                break
    for i in order:
        if ids[i]:
            continue
        b, loc = bases[i], locs[i] or "notice"
        sid, n = f"{b}~{loc}", 2
        while sid in taken:
            sid, n = f"{b}~{loc}-{n}", n + 1
        ids[i] = sid
        taken.add(sid)
    return ids


def build(paras: list[str], at: str, previous: list[dict]) -> tuple[list[dict], dict]:
    out: dict[str, dict] = {}
    bad = 0
    good: list[dict] = []
    for p in paras:
        try:
            good.append(read(p))
        except ValueError:
            pass
    ids = iter(assign_ids(good, previous))
    for p in paras:
        try:
            f = read(p)
        except ValueError as e:
            bad += 1
            text = strict_scrub(strip_house_numbers(scrub_text(p)))
            sid = "unread-" + hashlib.sha1(text.encode()).hexdigest()[:12]
            out[sid] = event(source_id=SOURCE_ID, source_record_id=sid, event_type="sso", status="unknown",
                             discharger_name=OPERATOR, discharger_id=OPERATOR_ID, npdes_permit=PERMIT, fetched_at=at,
                             authority=AUTHORITY,
                             source_url=URL, raw={"notice": text, "time_zone": TZ_NAME, "county": "Black Hawk County",
                                                  "city": "Waterloo", "state": "IA"},
                             parse_error=f"{error_detail(e)}: {text[:120]!r}")
            continue
        sid = next(ids)
        if home_place(f["text"], f["location"]):
            f = {**f, "location": None}
        raw = {"notice": strict_scrub(f["text"]), "location": strict_scrub(f["location"]), "cause": strict_scrub(f["cause"]),
               "permitted_overflow": f["permitted_overflow"], "bypass_pumping": f["bypass_pumping"],
               "start_basis": ("the notice gives the time the City was notified of the overflow (reported_at), not "
                               "when it began: the start is not stated" if f["notified"]
                               else "the time the notice says the City began the bypass"),
               "duration_minutes_as_stated": f["duration_minutes"],
               "county": "Black Hawk County", "city": "Waterloo", "state": "IA", "time_zone": TZ_NAME,
               "timezone_note": "Central time (the City's own clock)",
               "placement": ("the notice names no water and gives no point: listed with the City and Black Hawk County, "
                             "placed on no water"), "_last_seen_in_source": at,
               # never placed through the permit or the plant's receiving water (build/status.py own_place_only;
               # Astra 2026-11-15 P2-4)
               "_placement": "own_place_only"}
        if f["end"] is not None:
            raw.update(ended_at_precision="minute", end_basis=f["end_basis"])
        if f["end_note"]:
            raw["end_note"] = f["end_note"]
        if f["notified"] and f["duration_minutes"] is not None and f["end"] is None:
            raw["end_note"] = raw.get("end_note") or ("the notice states the event's duration but not when it began, "
                                                       "so no end is made from it")
        out[sid] = event(source_id=SOURCE_ID, source_record_id=sid, event_type="sso",
                         status="ended" if f["end"] else "unknown", discharger_name=OPERATOR,
                         discharger_id=OPERATOR_ID, npdes_permit=PERMIT,
                         started_at=None if f["notified"] else f["start"].isoformat(),
                         ended_at=f["end"].isoformat() if f["end"] else None,
                         time_precision="minute",
                         reported_at=f["start"].isoformat() if f["notified"] else None,
                         published_at=None, source_updated_at=None,
                         fetched_at=at, material="sewage", volume_gal=f["volume_gal"], volume_text=f["volume_text"],
                         estimate_flag="estimated" if f["volume_gal"] is not None else "unknown", authority=AUTHORITY,
                         source_url=URL, raw=raw)
    kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if not sid or sid in out:
            continue
        p = dict(p)
        p["raw"] = {**(p.get("raw") or {})}
        p["raw"].setdefault("_unlisted_since", at)
        for k in ("notice", "location", "cause"):          # the scrub again on what is carried from earlier runs
            if isinstance(p["raw"].get(k), str):
                p["raw"][k] = strict_scrub(p["raw"][k])
        if isinstance(p.get("parse_error"), str):
            p["parse_error"] = strict_scrub(p["parse_error"])
        if not sid.startswith("unread-"):
            p["raw"].setdefault("_placement", "own_place_only")
        if str(p["raw"].get("start_basis") or "").startswith("the time the City was notified") and p.get("started_at"):
            # saved before the fix: a notification time is the reported time, not a start, and an end made from it
            # plus a duration is not the source's (Astra 2026-11-15 P2-2)
            p["reported_at"], p["started_at"] = p["started_at"], None
            p["raw"]["start_basis"] = ("the notice gives the time the City was notified of the overflow (reported_at), "
                                       "not when it began: the start is not stated")
            if p["raw"].get("end_basis") == "the notice's start plus the duration it states":
                p["ended_at"], p["status"] = None, "unknown"
                for k in ("end_basis", "ended_at_precision"):
                    p["raw"].pop(k, None)
                p["raw"]["end_note"] = ("the notice states the event's duration but not when it began, so no end is "
                                        "made from it")
        out[sid] = p
        kept += 1
    recs = sorted(out.values(), key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r.get("event_id") or ""),
                  reverse=True)
    return recs, {"on_page": len(paras), "unreadable": bad, "kept_from_previous": kept}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        if "--file" in argv:
            page = Path(argv[argv.index("--file") + 1]).read_text()
        else:
            r = requests.get(URL, headers=HEADERS, timeout=120)
            r.raise_for_status()
            page = r.text
        paras = notices(page)
        if not paras and (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records"):
            raise ValueError("the list is empty where notices were listed before: a failed read")
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=error_detail(e))
        print(f"{SOURCE_ID}: {error_detail(e)}", file=sys.stderr)
        return 1
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    scrubbed = [strict_scrub(strip_house_numbers(scrub_text(p))) for p in paras]
    if "--file" not in argv and (prev_doc.get("meta") or {}).get("list_hash") != hashlib.sha1(
            json.dumps(scrubbed).encode()).hexdigest():
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "notices": scrubbed}, indent=1).encode(), "json")
    recs, stats = build(paras, at, prev_doc.get("records", []))
    meta = {"registry_ids": [SOURCE_ID], "url": URL, **stats,
            "list_hash": hashlib.sha1(json.dumps(scrubbed).encode()).hexdigest(),
            "cadence": "with the refresh; the City posts each notice after the event"}
    if stats["unreadable"]:
        # an unreadable notice is kept (parse_error) and read again next run; the feed is not healthy until it is read
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta,
                            error=f"{stats['unreadable']} notice(s) the reader cannot read")
    else:
        path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {stats['on_page']} notices on the page ({stats['unreadable']} unreadable); "
          f"{len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
