"""Louisville MSD's Overflow Advisory Level banner (Louisville and Jefferson County, Kentucky)
-> data/build/events/ky-louisville-msd-overflow-advisory.json.

Source
  The "Overflow Advisory Level" block that the Louisville/Jefferson County Metropolitan Sewer District shows on every
  page of louisvillemsd.org, read at https://louisvillemsd.org/overflowalert (registry
  ky-louisville-msd-overflow-advisory; research/ky/report.md section 2.3). An HTML block (Drupal
  block-overflowadvisoryblock-2) with a level class and one notice:
    level-1  "MSD-01 Wet Weather Overflows." with MSD's advice: "Recent rainfall has created the risk of sewer
             overflows in the Louisville Metro area. Avoid contact with water in the Ohio River, streams, drainage
             ditches and standing water until 48 hours after the rain has stopped." (system-wide; no time stamp in the
             block; 2024-02-29 and 2025-09-04 in the Internet Archive's copies, 2026-11-03 in the research)
    level-2  "MSD-02 <date> A Wet Weather Discharge has occurred" (or "A Dry Weather Discharge"): a dated notice with
             labelled lines: THIS REPORT CREATED AS OF, DATE AND TIME DISCHARGE BEGAN, ASSET ADDRESS, PROBLEM,
             COMPLETED DATE/TIME (a time or ONGOING), DISCHARGED AMOUNT, RECEIVING STREAM, IMPACT, MITIGATION, CLEAN UP
             (the Internet Archive's copy of 2025-02-19: a pump-station power outage to Pennsylvania Run)
    level-3  "Conditions are normal" (no advisory: grey, "no report", never clean)
  MSD removes old notices (the advisory pages of 2025 and 2026-11-03 answer 404), so the page is a snapshot: this
  module keeps data/build/ky-louisville-msd-state.json, every notice seen with the polls that saw it. The state file
  is the archive: do not delete it. Nothing in the block names a person; only the parsed block (level, title, text)
  is ever saved to data/raw/ (the rest of the page is navigation), and only when it changes.

Records (a status snapshot turned into events; il_mwrd_possible_cso.py and ri_nbc.py are the models)
  - MSD-01 (owner default, wave 4 brief): the authority's own advisory, quoted as MSD's, red while the banner stands.
    MSD's advice names the Ohio River and "streams" with no place, so it is attached to the receiving waters of MSD's
    open combined sewer outfalls: one record per open outfall of MSD's CSO permit KY0022411 in the outfall registry
    (data/outfalls-ky.json when present, else data/outfalls-us.json, closed rows left out), at the outfall's point
    (coord_source outfall_registry), so the stretch model draws each outfall's downstream reach; never a whole-water
    colour. event_type cso, status advisory_active, raw.advisory_scope "system-wide". The block gives no time, so
    started_at is the first poll that saw the banner (time_precision poll; raw.start_basis says so) and
    reported_at, published_at and source_updated_at stay null; raw._last_seen_in_source is the last poll that saw it.
    When a later complete poll no longer shows it, the records become advisory_lifted with ended_at that poll and
    raw.ended_at_precision "poll" (MSD withdrew it at or before then). MSD's "48 hours after the rain has stopped" is
    MSD's own rule; the banner's withdrawal is MSD's statement that it no longer applies.
  - MSD-02: a dated sewage report (event_type sso, or cso when the text names a combined sewer overflow) with MSD's
    times read in America/New_York (Jefferson County): started_at from DATE AND TIME DISCHARGE BEGAN (minute),
    ended_at from COMPLETED DATE/TIME when it gives a time (raw.ended_at_precision minute, status ended); ONGOING or
    blank leaves the end null (status ongoing), never invented; reported_at from THIS REPORT CREATED AS OF. Place:
    the receiving stream MSD names (waterbody_text, Jefferson County in raw.county); no point is given and none is
    invented (never the plant's point, never a geocoded address). The asset address is a public record of a street,
    kept only through the house-number scrub (common.strip_house_numbers via mi_egle_mienviro.free_text). The
    discharged amount is kept as MSD's words (volume_text); volume_gal only when it states one number of gallons.
    A notice that leaves the page while still ONGOING keeps its record with raw.left_page_at; its end is not invented
    (the status build's rule for a record with no end applies).
  - Any other level or title: an "unknown" record with parse_error, so a new advisory wording is seen, never dropped.
  - Conditions are normal: no record (grey).

Failures: a fetch that fails, or a page without the block, writes ok=False and keeps the previous records; the state
is not changed (a poll that could not read the page is not a withdrawal).

Run from pipeline/: python -m ingest.ky_louisville_msd [--file saved.html] [--at 2026-11-07T12:00:00Z]
Cadence: hourly with the refresh (a banner up for less than an hour between polls can be missed).
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "ky-louisville-msd-overflow-advisory"
URL = "https://louisvillemsd.org/overflowalert"
STATE_PATH = BUILD_DIR / "ky-louisville-msd-state.json"
TZ = ZoneInfo("America/New_York")      # Jefferson County (49 CFR 71.5(c): east of the boundary)
PERMIT = "KY0022411"                   # MSD's combined sewer permit (Morris Forman WQTC and the combined system)
DISCHARGER_ID = "ky-louisville-msd"
AUTHORITY = "Louisville/Jefferson County Metropolitan Sewer District (Overflow Advisory Level, louisvillemsd.org)"
BLOCK_RE = re.compile(r'<div id="block-overflowadvisoryblock-2"(.*?)(?=<div class="sidebar-col"|</body>|\Z)', re.S)
LEVEL_RE = re.compile(r'class="container (level-\d+)"')
CONTENT_RE = re.compile(r'<div class="overflow-content">(.*?)(?:<p class="footer">|</div>)', re.S | re.I)
H3_RE = re.compile(r"<h3>(.*?)</h3>", re.S | re.I)
LABEL_RE = re.compile(r"^\s*([A-Z][A-Z /&-]{2,40}?)\s*:\s*(.*)$")
MSD02_TITLE = re.compile(r"^MSD-02\s+(\d{1,2}/\d{1,2}/\d{4})\s+(.*)$")
MORE_INFO = re.compile(r"\s*For more information,.*$", re.S | re.I)
GALLONS = re.compile(r"^\s*(?:approx(?:imately|\.)?\s+)?([\d,]+(?:\.\d+)?)\s*(?:gal|gallons)\b\.?\s*$", re.I)
TIME_FORMATS = ("%m/%d/%Y %I:%M %p", "%m/%d/%Y at %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y")
MATERIAL_CSO = "combined sewage and stormwater"
MATERIAL_SSO = "untreated sewage"
MSD01_WINDOW_BASIS = ("MSD's advice: avoid contact \"until 48 hours after the rain has stopped\"; MSD gives no time for "
                      "it, so the advisory is shown while MSD's page carries it")
START_BASIS = ("the first poll of MSD's page that showed the banner: MSD's block gives no time, so the advisory began "
               "at or before then")


# ---------------------------------------------------------------- the page

def _text(fragment: str) -> str:
    """HTML to lines: <br> as a line break, tags dropped, entities read, spaces collapsed per line."""
    s = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def parse(page: str) -> dict:
    """{level, title, text} of the advisory block; ValueError when the page has no block."""
    m = BLOCK_RE.search(page or "")
    if not m:
        raise ValueError("no Overflow Advisory Level block on the page")
    block = m.group(1)
    lv = LEVEL_RE.search(block)
    c = CONTENT_RE.search(block)
    if not c:
        raise ValueError("the advisory block has no overflow-content")
    content = c.group(1)
    h3 = H3_RE.search(content)
    title = _text(h3.group(1)) if h3 else None
    body = _text(content[h3.end():] if h3 else content)
    return {"level": lv.group(1) if lv else None, "title": title, "text": body}


def code_of(snap: dict) -> str:
    """MSD-01, MSD-02, normal or unknown."""
    t = (snap.get("title") or "").strip()
    if t.upper().startswith("MSD-01"):
        return "MSD-01"
    if t.upper().startswith("MSD-02"):
        return "MSD-02"
    if t.lower().startswith("conditions are normal"):
        return "normal"
    return "unknown"


def fields(text: str) -> dict[str, str]:
    """An MSD-02 notice's labelled lines ('DATE AND TIME DISCHARGE BEGAN: 2/18/2025 3:15 PM'); a label alone on its
    line takes the next line as its value ('THIS REPORT CREATED AS OF:' then '2/18/2025 at 5:45 PM')."""
    out, pending = {}, None
    for ln in (text or "").split("\n"):
        m = LABEL_RE.match(ln)
        if m:
            label, value = m.group(1).strip().upper(), m.group(2).strip()
            if value:
                out[label], pending = value, None
            else:
                pending = label
        elif pending:
            out[pending], pending = ln.strip(), None
    return out


def local_time(v: str | None) -> tuple[str | None, str | None]:
    """(ISO time with Louisville's offset, precision) of MSD's '2/18/2025 3:15 PM'; (None, None) when unreadable."""
    v = re.sub(r"\s+", " ", (v or "").strip())
    for fmt in TIME_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if fmt == "%m/%d/%Y":
            return dt.date().isoformat(), "day"
        return dt.replace(tzinfo=TZ).isoformat(), "minute"
    return None, None


def scrub_address(v: str | None) -> str | None:
    """A street address through the house-number scrub (the asset's street is kept, its number is not)."""
    if not v:
        return v
    from ingest.mi_egle_mienviro import free_text
    return free_text(v)


# ---------------------------------------------------------------- the snapshot state

def _ident(code: str, snap: dict) -> str:
    """The notice's identity across polls: MSD-01 by its code (one banner at a time), MSD-02 by its begin time,
    asset and receiving stream, anything else by its title."""
    if code == "MSD-02":
        f = fields(snap.get("text"))
        basis = "|".join([snap.get("title") or "", f.get("DATE AND TIME DISCHARGE BEGAN", ""),
                          f.get("ASSET ADDRESS", ""), f.get("RECEIVING STREAM", "")])
        return "MSD-02:" + hashlib.sha1(basis.encode()).hexdigest()[:12]
    if code == "MSD-01":
        return "MSD-01"
    return "unknown:" + hashlib.sha1((snap.get("title") or "").encode()).hexdigest()[:12]


def update(state: dict, snap: dict, fetched_at: str) -> dict:
    """The state after one complete poll: the notice on the page opened or confirmed; every open notice not on the
    page closed at this poll (left_at)."""
    apps = state.setdefault("appearances", [])
    code = code_of(snap)
    ident = _ident(code, snap) if code != "normal" else None
    for a in apps:
        if a.get("left_at") is None and a["ident"] != ident:
            a["left_at"] = fetched_at
    state["last_poll"] = {"at": fetched_at, "code": code, "level": snap.get("level"), "title": snap.get("title")}
    if ident is None:
        return state
    cur = next((a for a in apps if a["ident"] == ident and a.get("left_at") is None), None)
    if cur is None:
        cur = {"ident": ident, "code": code, "key": f"{ident.split(':')[0]}:{fetched_at}", "first_seen": fetched_at}
        apps.append(cur)
    cur.update({"last_seen": fetched_at, "level": snap.get("level"), "title": snap.get("title"),
                "text": snap.get("text")})
    return state


# ---------------------------------------------------------------- records

def msd_outfalls() -> list[dict]:
    """MSD's open CSO outfalls (permit KY0022411) with a point: data/outfalls-ky.json when it lists the permit, else
    EPA's national inventory; closed rows (CLS) left out."""
    for name in ("outfalls-ky.json", "outfalls-us.json"):
        doc = read_json(DATA_DIR / name, {}) or {}
        rows = [o for o in (doc.get("outfalls") or []) if o.get("npdes_permit") == PERMIT
                and not str(o.get("outfall_status") or "").upper().startswith("CLS") and o.get("lat") is not None]
        if rows:
            return sorted(rows, key=lambda o: str(o.get("outfall")))
    return []


def advice(text: str) -> str:
    return "MSD: “" + MORE_INFO.sub("", " ".join((text or "").split())).strip() + "”"


def msd01_records(a: dict, outfalls: list[dict]) -> list[dict]:
    left = a.get("left_at")
    out = []
    for o in outfalls:
        raw = {"advisory_code": "MSD-01", "advisory_title": a.get("title"),
               "advisory_text": MORE_INFO.sub("", " ".join((a.get("text") or "").split())).strip(),
               "advisory_level": a.get("level"), "advisory_scope": "system-wide",
               "scope_note": ("MSD's advisory covers the Louisville Metro area's waters; shown at each of MSD's open "
                              "combined sewer outfalls, whose downstream reach it colours"),
               "first_seen_at": a["first_seen"], "_last_seen_in_source": a.get("last_seen"),
               "start_basis": START_BASIS, "time_zone": "America/New_York", "county": "Jefferson",
               "outfall_source": o.get("source_id") or "EPA National CSO Inventory (ICIS-NPDES permitted features)"}
        if left:
            raw.update({"left_page_at": left, "ended_at_precision": "poll",
                        "end_basis": "the first poll of MSD's page that no longer showed the banner: MSD withdrew it "
                                     "at or before then"})
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"{a['key']}:{o['outfall']}", event_type="cso",
            status="advisory_lifted" if left else "advisory_active",
            discharger_id=DISCHARGER_ID, discharger_name="Louisville/Jefferson County Metropolitan Sewer District",
            npdes_permit=PERMIT, outfall_id=str(o["outfall"]), outfall_name=o.get("outfall_name") or None,
            waterbody_text=o.get("water_name") or o.get("receiving_water_echo") or None,
            water_slugs=[o["water_slug"]] if o.get("water_slug") else [],
            water_match="outfall_registry" if o.get("water_slug") else "none",
            lat=o["lat"], lon=o["lon"], coord_source="outfall_registry",
            started_at=a["first_seen"], ended_at=left, time_precision="poll",
            reported_at=None, published_at=None, source_updated_at=None,
            material=MATERIAL_CSO, authority=AUTHORITY, advice_text=advice(a.get("text")),
            advice_window_hours=None, advice_window_basis=MSD01_WINDOW_BASIS,
            source_url=URL, raw=raw))
    return out


def msd02_record(a: dict) -> dict:
    f = fields(a.get("text"))
    t = MSD02_TITLE.match(a.get("title") or "")
    started, sp = local_time(f.get("DATE AND TIME DISCHARGE BEGAN"))
    if not started and t:
        started, sp = local_time(t.group(1))
    done = (f.get("COMPLETED DATE/TIME") or "").strip()
    ended, ep = (None, None) if not done or done.upper().startswith("ONGOING") else local_time(done)
    created, _ = local_time((f.get("THIS REPORT CREATED AS OF") or "").replace(" at ", " "))
    whole = " ".join([a.get("title") or "", a.get("text") or ""])
    etype = "cso" if re.search(r"\bcso\b|combined sewer overflow", whole, re.I) else "sso"
    amount = f.get("DISCHARGED AMOUNT")
    g = GALLONS.match(amount or "")
    stream = f.get("RECEIVING STREAM")
    perr = None if started else "no readable begin time"
    if done and not done.upper().startswith("ONGOING") and not ended:
        perr = (perr + "; " if perr else "") + f"completion time not read: {done!r}"
    raw = {"advisory_code": "MSD-02", "advisory_title": a.get("title"), "notice_kind": t.group(2) if t else None,
           "problem": f.get("PROBLEM"), "impact": f.get("IMPACT"), "mitigation": f.get("MITIGATION"),
           "clean_up": f.get("CLEAN UP"), "completed_as_given": done or None,
           "asset_address": scrub_address(f.get("ASSET ADDRESS")), "receiving_stream_as_given": stream,
           "county": "Jefferson", "time_zone": "America/New_York",
           "first_seen_at": a["first_seen"], "_last_seen_in_source": a.get("last_seen"),
           "placement_note": "MSD names the receiving stream and gives no point: placed by the stream's name only"}
    if ended:
        raw["ended_at_precision"] = ep
    if a.get("left_at"):
        raw["left_page_at"] = a["left_at"]
    return event(
        source_id=SOURCE_ID, source_record_id=a["key"], event_type=etype,
        status="ended" if ended else "ongoing",
        discharger_id=DISCHARGER_ID, discharger_name="Louisville/Jefferson County Metropolitan Sewer District",
        waterbody_text=stream.title() if stream else None, water_slugs=[], water_match="none",
        started_at=started, ended_at=ended, time_precision=sp,
        reported_at=created, published_at=None, source_updated_at=None,
        material=MATERIAL_CSO if etype == "cso" else MATERIAL_SSO,
        volume_gal=int(float(g.group(1).replace(",", ""))) if g else None, volume_text=amount or None,
        estimate_flag="estimated" if amount else "unknown", authority=AUTHORITY,
        source_url=URL, raw=raw, parse_error=perr)


def unknown_record(a: dict) -> dict:
    return event(source_id=SOURCE_ID, source_record_id=a["key"], event_type="unknown", status="unknown",
                 discharger_id=DISCHARGER_ID, discharger_name="Louisville/Jefferson County Metropolitan Sewer District",
                 started_at=a["first_seen"], ended_at=None, time_precision="poll", authority=AUTHORITY,
                 source_url=URL, raw={"advisory_title": a.get("title"), "advisory_text": a.get("text"),
                                      "advisory_level": a.get("level"), "first_seen_at": a["first_seen"],
                                      "_last_seen_in_source": a.get("last_seen"), "left_page_at": a.get("left_at")},
                 parse_error=f"advisory wording not recognised: {a.get('title')!r}")


def records(state: dict, outfalls: list[dict] | None = None) -> list[dict]:
    outfalls = msd_outfalls() if outfalls is None else outfalls
    out = []
    for a in state.get("appearances", []):
        if a["code"] == "MSD-01":
            out += msd01_records(a, outfalls)
        elif a["code"] == "MSD-02":
            out.append(msd02_record(a))
        else:
            out.append(unknown_record(a))
    out.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    return out


# ---------------------------------------------------------------- run

def fetch() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        page = Path(argv[argv.index("--file") + 1]).read_text() if "--file" in argv else fetch()
        snap = parse(page)
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    state = read_json(STATE_PATH, {}) or {}
    prev = (state.get("last_poll") or {})
    if "--file" not in argv and (prev.get("title"), prev.get("level")) != (snap.get("title"), snap.get("level")):
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, **snap}, indent=1).encode(), "json")   # the block only
    state = update(state, snap, at)
    write_json(STATE_PATH, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "last_poll": state.get("last_poll"),
            "appearances": len(state.get("appearances", [])), "msd_outfalls": len(msd_outfalls()),
            "cadence": "hourly with the refresh; MSD removes old notices, so the state file is the archive"}
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {code_of(snap)} ({snap.get('title')!r}); {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
