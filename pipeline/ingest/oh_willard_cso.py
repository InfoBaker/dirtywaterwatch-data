"""City of Willard CSO public notifications -> data/build/events/oh-willard-cso-notices.json.

Source (registry oh-willard-cso-notices; 40 CFR 122.38, the Great Lakes CSO public notice rule)
  Willard's "Combined Sewer Overflows (CSO)" page, https://www.willardohio.gov/cso.html (a Weebly page; 200 to this
  machine and GitHub's runner, 2026-11-16). Under "PUBLIC NOTIFICATION" the city posts each overflow's notices as
  HTML: a heading "INITIAL NOTIFICATION: <Month D, YYYY>" (the four-hour notice) or "SUPPLEMENTAL NOTIFICATION:
  <date>" (the notice after the end), then labelled lines: "Date and Time (the) CSO began", "Date and Time CSO
  ended", "TOTAL DURATION", "Location of discharge" (the city's CSO holding lagoon), "Discharge stream" (Jacob Creek),
  "Treatment provided", "Status at time of this notification", "Areas affected" (several lines), "Rainfall prior to
  beginning", "Total Rainfall this CSO event", "TOTAL CSO VOLUME", then "For more information contact" and the staff
  contacts. 2026-11-16: four notices, two overflows (2025-04-05 and 2026-04-01).
  Read: only the labelled lines above, from the page's own section (between the "PUBLIC NOTIFICATION" heading and the
  "CSO Contact Request Form"); reading of each notice stops at "For more information contact". The page names staff
  with telephone numbers and e-mail addresses: they are never read, saved or logged, and the page itself is never
  saved (save_raw gets the parsed notices only).

Records
  - One cso record per overflow. The initial and the supplemental notice of one overflow are one record: both state
    the start ("Date and Time the CSO began"), and the record's key is that start, local YYYYMMDDTHHMM (Willard
    writes "04/1/2026 2:45 pm" in one and "04/01/2026 2:45 pm" in the other; both read as the same minute). The
    supplemental notice revises the initial one (end, volume, total rainfall, status); raw.notices lists every notice
    read, with its kind and heading date. Two notices whose starts differ are two records: no other evidence ties
    them (a start corrected between the notices would show as two records, the earlier with no end).
  - started_at and ended_at as written, to the minute, America/New_York: the page states no zone and Willard (Huron
    County) keeps Eastern time; an hour that repeats when daylight time ends is read as its first occurrence
    (raw.time_zone). No end is ever invented: an overflow with only its initial notice has ended_at null and status
    ongoing while that notice says "active", else unknown (end not confirmed). A notice that says the overflow ended
    but gives no end time leaves ended_at null and status unknown.
  - The heading date is the notice's date (raw.notices[].notice_date, day precision): a publication day, never a
    start; published_at stays null because the page gives no time of posting. reported_at and source_updated_at null.
  - volume_gal from "TOTAL CSO VOLUME" in million gallons (or gallons, as written); volume_text as written;
    estimate_flag unknown (the page does not say how it is measured). Rainfall, duration, treatment and the areas the
    city names as affected are kept in raw.
  - Place: permit OH0028118 (City of Willard; data/dischargers.json oh-willard-wpcp-oh0028118). The notices name no
    outfall number: the registry's three CSO outfalls (007, 008, 009, "CSO Monitoring" on Holliday Lake) cannot be
    told apart from "the CSO holding lagoon", so no outfall and no point are tied (a wrong tie is worse than none);
    raw.discharge_stream is the discharge stream as named ("Jacob Creek"), raw.areas_affected the waters and places the
    city names downstream. waterbody_text joins the two in the city's words ("Jacob Creek; areas affected: West
    Branch of Huron River, Holiday Lakes, Monroeville"): Jacob Creek and the West Branch have no water record
    (2026-11-16), so the status build places the record on Holiday Lakes by name, the lake the city names as affected
    and the one the registry gives as the receiving water of the three CSO outfalls ("Holliday Lake").
  - advice_text null: the notices give no advice.
  Privacy: only the labelled fields are kept; a location line holding a street number or a ZIP code (the lagoon's
  street address) is dropped; common.event runs strip_personal.

State: data/build/oh-willard-cso-state.json keeps every notice read (its parsed fields only): a notice that leaves
  the page stays a past report. Do not delete it.
Failures: a failed request, a page without its CSO section, a notification heading whose notice cannot be read (no
  start), or a section with no notice heading and without the city's "none at this time" sentence is a failed read:
  ok=False, the previous records kept, the state unchanged. One unreadable notice among readable ones: the readable
  ones are saved and published, the unread one is named in the error and health stays false (partial) until it reads.
History: the page itself is the only archive (no older pages); there is no --backfill.
Run from pipeline/: python -m ingest.oh_willard_cso [--file saved.html --out events.json]
Cadence: hourly with the refresh (Ohio is live).
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

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "oh-willard-cso-notices"
URL = "https://www.willardohio.gov/cso.html"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "OH0028118"
DISCHARGER = "City of Willard"
STATE_PATH = BUILD_DIR / "oh-willard-cso-state.json"
CREDIT = "City of Willard, CSO public notification"
MATERIAL = "combined sewage and stormwater"
NONE_SENTENCE = re.compile(r"There are currently none at this time", re.I)

# the labelled lines of a notice, in the city's own words (case and "the" vary between notices)
LABELS = [
    ("start", re.compile(r"^Date and Time (?:the )?CSO began\s*:?\s*", re.I)),
    ("end", re.compile(r"^Date and Time (?:the )?CSO ended\s*:?\s*", re.I)),
    ("duration", re.compile(r"^TOTAL DURATION\s*:?\s*", re.I)),
    ("location", re.compile(r"^Location of discharge\s*:?\s*", re.I)),
    ("stream", re.compile(r"^Discharge stream\s*:?\s*", re.I)),
    ("treatment", re.compile(r"^Treatment provided\s*:?\s*", re.I)),
    ("status", re.compile(r"^Status at time of this notification\s*:?\s*", re.I)),
    ("areas", re.compile(r"^Areas affected\s*:?\s*", re.I)),
    ("rain_before", re.compile(r"^Rainfall prior to beginning\s*:?\s*", re.I)),
    ("rain_total", re.compile(r"^Total Rainfall this CSO event\s*:?\s*", re.I)),
    ("volume", re.compile(r"^TOTAL CSO VOLUME\s*:?\s*", re.I)),
]
STOP = re.compile(r"^For more information", re.I)          # the staff contacts follow: never read
KIND = re.compile(r"^(INITIAL|SUPPLEMENTAL)\s+NOTIFICATION\s*:?\s*(.*)$", re.I)
OTHER_HEADING = re.compile(r"^(?!PUBLIC\b)[A-Z][A-Z -]*\bNOTIFICATION\b\s*:")
INLINE = re.compile(r"</?(?:span|u|strong|em|font|b|i|a|sup|sub)\b[^>]*>", re.I)
BREAK = re.compile(r"<br\s*/?>|</?(?:div|p|h\d|li|tr|td|table|tbody)\b[^>]*>", re.I)


class LayoutError(ValueError):
    """The page no longer has the section or headings this reader knows: a failed read, never "no overflows"."""


def text_lines(fragment: str) -> list[str]:
    """Lines of an HTML fragment: breaks and blocks end a line; inline tags are dropped without a space (the page
    splits words across spans: "J</span><span>acob Creek")."""
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", fragment)
    t = BREAK.sub("\n", INLINE.sub("", t))
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("​", "").replace("\xa0", " ")
    return [" ".join(x.split()) for x in t.split("\n") if x.strip() and x.strip() != "​"]


def section(page: str) -> str:
    """The page's own notice section: from the "PUBLIC NOTIFICATION" title to the contact request form's heading."""
    i = re.search(r"PUBLIC NOTIFICATION\s*</", page)
    j = re.search(r"CSO Contact Request Form\s*</h2>", page[i.end():]) if i else None
    if not i or not j:
        raise LayoutError("the page's PUBLIC NOTIFICATION section was not found")
    return page[i.end():i.end() + j.start()]


def read_fields(lines: list[str]) -> dict:
    """The labelled fields of one notice; a line with no label continues the previous field."""
    f: dict[str, list[str]] = {}
    cur = None
    for ln in lines:
        if STOP.match(ln):
            break
        for name, rx in LABELS:
            m = rx.match(ln)
            if m:
                cur = name
                f.setdefault(name, [])
                rest = ln[m.end():].strip()
                if rest:
                    f[name].append(rest)
                break
        else:
            if cur:
                f[cur].append(ln)
    return {k: v for k, v in f.items()}


def joined(v: list[str] | None, sep: str = " ") -> str | None:
    s = sep.join(x for x in (v or []) if x).strip()
    return s or None


def local(v: str | None) -> datetime | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?", v or "", re.I)
    if not m:
        return None
    mo, d, y, h, mi, ap = m.groups()
    h = int(h) % 12 + (12 if ap.lower() == "p" else 0)
    try:
        return datetime(int(y), int(mo), int(d), h, int(mi), tzinfo=TZ)     # fold 0: the first of a repeated hour
    except ValueError:
        return None


def notice_day(v: str) -> str | None:
    try:
        return datetime.strptime(" ".join(v.replace(",", ", ").split()), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def volume_gallons(v: str | None) -> int | None:
    m = re.search(r"(\d[\d,]*\.?\d*|\.\d+)\s*(million gallons|MG\b|gallons)", v or "", re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    return int(round(n * 1_000_000)) if unit in ("million gallons", "mg") else int(round(n))


def place_lines(v: list[str] | None) -> list[str]:
    """The location lines without the street address (a line starting with a number, or holding a ZIP code)."""
    return [x for x in (v or []) if not re.match(r"^\d", x) and not re.search(r"\b\d{5}(?:-\d{4})?\b", x)]


def parse(page: str) -> tuple[list[dict], list[str]]:
    """(notices read, notices not read with the reason). Raises LayoutError when the section is not there.

    The notice headings are marked up in several ways (an h2, or large type at the head of a paragraph), so the section
    is read as lines and a notice starts at each line "INITIAL NOTIFICATION: <date>" or "SUPPLEMENTAL NOTIFICATION:
    <date>"; another capitalised "... NOTIFICATION" line is a heading this reader does not know (an unread notice)."""
    lines = text_lines(section(page))
    blocks: list[tuple[str, list[str]]] = []
    for ln in lines:
        if KIND.match(ln) or OTHER_HEADING.match(ln):
            blocks.append((ln, []))
        elif blocks:
            blocks[-1][1].append(ln)
    notices, unread = [], []
    for title, body in blocks:
        km = KIND.match(title)
        if not km:
            unread.append(f"heading '{title[:60]}': not an initial or supplemental notification")
            continue
        f = read_fields(body)
        st = local(joined(f.get("start")))
        if st is None:
            unread.append(f"{km.group(1).lower()} notice of {km.group(2)[:30]}: no start read")
            continue
        end_text = joined(f.get("end"))
        end = local(end_text)
        if end_text and end is None:
            unread.append(f"{km.group(1).lower()} notice of {km.group(2)[:30]}: end '{end_text[:30]}' not read")
            continue
        notices.append({
            "kind": km.group(1).lower(), "notice_date": notice_day(km.group(2)), "notice_heading": title,
            "start_text": joined(f.get("start")), "start": st.isoformat(),
            "end_text": end_text, "end": end.isoformat() if end else None,
            "duration": joined(f.get("duration")), "location": joined(place_lines(f.get("location")), ", "),
            "stream": joined(f.get("stream")), "treatment": joined(f.get("treatment")),
            "status_text": joined(f.get("status")), "areas_affected": [x for x in f.get("areas") or [] if x],
            "rain_before": joined(f.get("rain_before")), "rain_total": joined(f.get("rain_total")),
            "volume_text": joined(f.get("volume")),
        })
    if not blocks and not NONE_SENTENCE.search(" ".join(lines)):
        raise LayoutError("no notification heading and no 'none at this time' sentence in the section")
    return notices, unread


def notice_key(n: dict) -> str:
    return f"{n['kind']}:{n['start']}:{n.get('notice_date') or ''}"


def said_active(text: str | None) -> bool | None:
    """True for "active", False for "not active" or "ended", None otherwise (negation first)."""
    t = (text or "").lower()
    if re.search(r"\bnot active\b|\binactive\b|\bended\b|\bhas ended\b|\bstopped\b", t):
        return False
    if re.search(r"\bactive\b|\bongoing\b|\bcontinu", t):
        return True
    return None


def water_text(stream: str | None, areas: list[str] | None) -> str | None:
    """The discharge stream as named, then the areas the city names as affected, in its words: "Jacob Creek; areas
    affected: West Branch of Huron River, Holiday Lakes, Monroeville"."""
    if areas:
        return f"{stream or 'stream not named'}; areas affected: {', '.join(areas)}"
    return stream


def to_record(key: str, notices: list[dict]) -> dict:
    notices = sorted(notices, key=lambda n: (n["kind"] == "supplemental", n.get("notice_date") or "",
                                             n["first_seen_at"]))
    latest = notices[-1]

    def last(field):
        for n in reversed(notices):
            if n.get(field) not in (None, "", []):
                return n[field]
        return None
    st = datetime.fromisoformat(notices[0]["start"])
    end = last("end")
    active = said_active(latest.get("status_text"))
    status = "ended" if end else ("ongoing" if active is True and latest["kind"] == "initial" else "unknown")
    vol_text = last("volume_text")
    gal = volume_gallons(vol_text)
    raw = {"time_zone": TZ_NAME, "state": "OH",
           "notices": [{"kind": n["kind"], "notice_date": n.get("notice_date"), "start_as_written": n["start_text"],
                        "end_as_written": n.get("end_text"), "status_at_notice": n.get("status_text"),
                        "_first_seen_at": n["first_seen_at"], "_last_seen_in_source": n["last_seen_at"]}
                       for n in notices],
           "discharge_stream": last("stream"), "duration": last("duration"), "treatment": last("treatment"), "location": last("location"),
           "areas_affected": last("areas_affected") or [], "rainfall_before": last("rain_before"),
           "rainfall_total": last("rain_total"),
           "_last_seen_in_source": max(n["last_seen_at"] for n in notices),
           "place_basis": (f"the notices name the city's CSO holding lagoon and the discharge stream, not an outfall "
                           f"number; permit {PERMIT}'s three registry CSO outfalls (007, 008, 009) cannot be told "
                           "apart from that, so no outfall or point is tied"),
           "time_note": ("times as the notices write them, read as Eastern time (America/New_York): the page states "
                         "no zone; a heading date is the notice's date, not the overflow's start"),
           "key_note": "one record per overflow: the initial and supplemental notices share the start they state"}
    if end:
        raw["ended_at_precision"] = "minute"
    elif latest["kind"] == "supplemental" or active is False:
        raw["end_note"] = "a notice says the overflow ended but gives no end time: end not confirmed"
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status=status,
        discharger_name=DISCHARGER, npdes_permit=PERMIT, outfall_id=None,
        outfall_name="CSO holding lagoon" if re.search(r"lagoon", last("location") or "", re.I) else None,
        waterbody_text=water_text(last("stream"), last("areas_affected")), lat=None, lon=None, coord_source=None,
        started_at=st.isoformat(), ended_at=end, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=None,
        fetched_at=max(n["last_seen_at"] for n in notices), material=MATERIAL,
        volume_gal=gal, volume_text=vol_text, estimate_flag="unknown",
        authority=CREDIT, advice_text=None, source_url=URL, raw=raw)


def run(notices: list[dict], now: str, state_path: Path) -> tuple[list[dict], dict]:
    """Merge the notices read now into the state, then one record per start from every notice ever read."""
    state = read_json(state_path, {}) or {}
    held = state.setdefault("notices", {})
    for n in notices:
        k = notice_key(n)
        prev = held.get(k) or {}
        held[k] = {**n, "first_seen_at": prev.get("first_seen_at") or now, "last_seen_at": now}
    state["last_read"] = {"at": now, "notices": len(notices)}
    write_json(state_path, state)
    by_start: dict[str, list[dict]] = {}
    for n in held.values():
        key = datetime.fromisoformat(n["start"]).strftime("%Y%m%dT%H%M")
        by_start.setdefault(key, []).append(n)
    recs = [to_record(k, v) for k, v in by_start.items()]
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    return recs, {"registry_ids": [SOURCE_ID], "url": URL, "notices_read": len(notices),
                  "notices_held": len(held), "credit": CREDIT}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    out = Path(a.out) if a.out else None
    if a.file and not out:
        ap.error("--file needs --out")
    state_path = out.with_suffix(".state.json") if a.file else STATE_PATH
    try:
        if a.file:
            page = Path(a.file).read_text(errors="replace")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(20, 90))
            r.raise_for_status()
            page = r.text
        notices, unread = parse(page)
    except (requests.RequestException, LayoutError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    if not a.file:
        save_raw(SOURCE_ID, json.dumps(notices), "json")          # the parsed notices only, never the page
    recs, meta = run(notices, now, state_path)
    if unread:
        meta["unread"] = unread
        write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, path=out,
                     error="notices not read: " + "; ".join(unread))
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; not read: {unread}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records from {len(notices)} notices -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
