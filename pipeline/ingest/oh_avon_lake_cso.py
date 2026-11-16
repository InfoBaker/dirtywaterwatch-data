"""Avon Lake Regional Water CSO notices, Form B (PDF) -> data/build/events/oh-avon-lake-cso-notices.json.

Source (registry oh-avon-lake-cso-notices; 40 CFR 122.38, the Great Lakes CSO public notice rule)
  Avon Lake Regional Water's water reclamation facility page,
  https://avonlakewater.org/about-us/about-the-avon-lake-water-reclamation-facility/ (200 to this machine and GitHub's
  runner, 2026-11-16), links one PDF per overflow: "Form B, Supplemental Notification of CSO" (46 on 2026-11-16, from
  2019 to 2026-08-22; the initial notices are not posted). Each form gives: Date (of the form), "Lake Erie receives the
  discharge", Initial Notification sent (a date), Start time of CSO discharge ("1800 8/22/2026", a 24-hour time and a
  date), CSO Outfall Information ("Center Road Pump Station"), Outfall Number (17), Flow observed, Impacted areas
  ("Lake Erie from Miller Road to Lear Road") with Yes or No for Veteran's Memorial Park, Avon Lake Boat Club, Lake
  Erie and Miller Road, End time of CSO discharge, End time of rain event, Estimated Volume of discharge ("0.9 Million
  Gallons"), then the inspector's initials and a staff name and telephone (never read or saved), precipitation and
  notes. A notice link is a PDF whose name says "form-B" (any case); the annual notices and the notification plan are
  not read.

Records
  - One cso record per overflow: source_record_id the start, local YYYYMMDDTHHMM; a second form of the same start
    revises it (the later one read wins; raw.notices lists both).
  - started_at: the start time and the date written with it, minute, America/New_York (the forms state no zone;
    Avon Lake keeps Eastern time; a repeated fall-back hour is read as its first occurrence). Many forms of 2019 to
    2023 give a start time with no date ("1745"): the form's date and the date the initial notice was sent are notice
    dates, never the start's, so such a form makes no record; it is listed in meta.no_start_date with its address
    (read, not a failure: the form has no start date to read).
  - ended_at: the end time with its own date. An end time with no date ("1250") is not dated from the start: ended_at
    null, status unknown, raw.end_as_written keeps it and raw.end_note says so. An end before the start is not used,
    the same way. No end is ever invented.
  - volume: "Million Gallons" or "MG" gives volume_gal, estimate_flag estimated (the form says "Estimated"); "MGD" (a
    rate) or no unit gives volume_text as written and no gallons (raw.volume_note says why).
  - Place: permit OH0023981 (Avon Lake Regional Water; data/dischargers.json). The form's outfall number is tied to
    the registry's outfall of the same number only when that row is an open CSO outfall with its own point (17 is
    017, Center Road, Lake Erie, on 2026-11-16): outfall_id, the registry's point (coord_source outfall_layer).
    waterbody_text the water the form names as receiving the discharge ("Lake Erie"); the impacted areas and the
    Yes/No list in raw.impacted_areas.
  - Times: published_at, reported_at, source_updated_at null; the form's date and the initial notice's date are kept
    in raw.notices (notice dates, day precision). fetched_at and raw._last_seen_in_source the last read that listed it.
  Privacy: only the fields above are parsed; the inspector's initials and the contact line are never read.

State: data/build/oh-avon-lake-cso-state.json (oh_cso_pdf_notices: every notice read, by address). Do not delete it.
Failures, unread notices: oh_cso_pdf_notices.run_feed.
History: the page lists every form since 2019; the first run reads them all (46 requests), later runs only new ones.
  No --backfill.
Run from pipeline/: python -m ingest.oh_avon_lake_cso [--index saved.html --texts texts.json --out events.json]
Cadence: hourly with the refresh (Ohio is live).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from common import BUILD_DIR, event, load_outfall_registry, now_iso, outfall_number
from ingest import oh_cso_pdf_notices as PN

SOURCE_ID = "oh-avon-lake-cso-notices"
INDEX_URL = "https://avonlakewater.org/about-us/about-the-avon-lake-water-reclamation-facility/"
LINK = re.compile(r"/wp-content/uploads/[^/]*form-?B[^/]*\.pdf$", re.I)
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "OH0023981"
DISCHARGER = "Avon Lake Regional Water"
STATE_PATH = BUILD_DIR / "oh-avon-lake-cso-state.json"
CREDIT = "Avon Lake Regional Water, CSO notice (Form B)"
MATERIAL = "combined sewage and stormwater"
DATE = r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})\b"
YESNO = ("Veteran's Memorial Park", "Avon Lake Boat Club", "Lake Erie", "Miller Road Park", "Miller Roa")


def local(hm: tuple[str, str], d: tuple[str, str, str]) -> datetime | None:
    mo, dd, y = (int(x) for x in d)
    y = y + 2000 if y < 100 else y
    try:
        return datetime(y, mo, dd, int(hm[0]), int(hm[1]), tzinfo=TZ)
    except ValueError:
        return None


LABEL_LINE = re.compile(r"^[A-Z][A-Za-z #'/]{1,40}:")


def value(ls: list[str], label: str, colon: bool = True) -> str | None:
    """The value after a label; an empty value continues on the next line when that line is not another label
    (the layout can wrap it; review 2026-11-16 P1)."""
    for k, ln in enumerate(ls):
        m = re.match(r"\s*" + label + (r"\s*:\s*(.*)$" if colon else r"\s*:?\s+(\S.*)$"), ln, re.I)
        if m:
            v = m.group(1).strip()
            if not v and k + 1 < len(ls) and not LABEL_LINE.match(ls[k + 1]):
                v = ls[k + 1].strip()
            return v
    return None


def when(v: str | None) -> tuple[datetime | None, str | None]:
    """(time, problem) from a form's "1800 8/22/2026", "500 10/21/2020" or "2000 on 6/29/2021": the 24-hour time
    must open the value (three or four digits; "500" is 05:00) and a date must follow it. Digits inside the date are
    never read as the time. A time with no date, or no value, is a problem."""
    if not v or not v.strip():
        return None, "not given"
    m = re.match(r"\s*~?\s*(\d{3,4})\b(.*)$", v)
    if not m:
        return None, f"'{v[:30]}' has no date" if not re.search(DATE, v) else f"'{v[:30]}' has no 24-hour time"
    hhmm = m.group(1).zfill(4)
    d = re.search(DATE, m.group(2))
    if not d:
        return None, f"'{v[:30]}' has no date"
    h, mi = int(hhmm[:2]), int(hhmm[2:])
    if h > 23 or mi > 59:
        return None, f"'{v[:30]}' has no 24-hour time"
    dt = PN.existing(local((str(h), str(mi)), d.groups()))
    return (dt, None) if dt else (None, f"'{v[:30]}' not a date and time")


NO_START_DATE = ("not given", "has no date")
MONTHS = re.compile(r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*$", re.I)


def receiving_water(joined: str) -> str | None:
    """The water the form names before "receives the discharge" ("Lake Erie"), without the form date's month that
    the layout text can run into it ("Dec Lake Erie")."""
    m = re.search(r"((?:[A-Z][a-z]+ ){0,3}[A-Z][a-z]+) receives the discharge", joined)
    if not m:
        return None
    words = m.group(1).split()
    while words and MONTHS.match(words[0]):
        words.pop(0)
    return " ".join(words) or None


def parse(text: str) -> dict:
    """The fields of one Form B; NoticeError when it is not Avon Lake's form."""
    ls = PN.lines(text)
    joined = " ".join(ls)
    if not re.search(r"\bForm B\b", joined) or not re.search(r"Start time of CSO discharge", joined, re.I):
        raise PN.NoticeError("not Avon Lake's Form B")
    start_raw = value(ls, r"Start time of CSO discharge")
    end_raw = value(ls, r"End time of CSO discharge")
    st, st_problem = when(start_raw)
    if st is None and not (st_problem or "").endswith(NO_START_DATE):
        raise PN.NoticeError(f"start {st_problem}")
    end, end_problem = when(end_raw)
    dl = next((x for x in ls if x.startswith("Date:")), None)
    form_date = " ".join(re.sub(r"[A-Z][A-Za-z .'-]{2,40}? receives the discharge", " ", dl[5:]).split()) if dl else None
    vol = value(ls, r"Estimated Volume of discharge")
    areas = {}
    for k in YESNO:
        v = value(ls, re.escape(k) + (r"(?!d)" if k == "Miller Roa" else ""), colon=False)
        if v and re.fullmatch(r"(?i)yes|no", v) and not (k == "Miller Roa" and "Miller Road Park" in areas):
            areas[k] = v
    sent = value(ls, r"Initial Notification sent")
    return {"kind": "supplemental" if re.search(r"\bSupplemental\b", joined) else "notice",
            "start": st.isoformat() if st else None, "start_as_written": start_raw, "start_problem": st_problem,
            "end": end.isoformat() if end else None, "end_as_written": end_raw or None,
            "end_problem": end_problem if end_raw else None,
            "form_date": form_date or None,
            "initial_notice_sent": sent, "outfall_info": value(ls, r"CSO Outfall Information"),
            "outfall_number": (value(ls, r"Outfall Number") or "").split()[0] if (value(ls, r"Outfall Number") or "").split()
            else None,
            "water": receiving_water(joined), "impacted_areas": value(ls, r"Impacted areas"),
            "impacted_yes_no": areas, "volume_as_written": vol}


def volume(v: str | None) -> tuple[int | None, str | None]:
    """(gallons, note) from "0.9 Million Gallons", "3.5 MG"; a rate (MGD) or a bare number gives no gallons."""
    m = re.search(r"~?\s*(\d*\.?\d+)\s*(million gallons|MGD|MG)?\b", v or "", re.I)
    if not m:
        return None, None
    unit = (m.group(2) or "").lower()
    if unit in ("million gallons", "mg"):
        return int(round(float(m.group(1)) * 1_000_000)), None
    if unit == "mgd":
        return None, "the form gives MGD, a daily rate, not a volume: no gallon figure is given"
    return None, "the form gives no unit: no gallon figure is given"


def volume_text(v: str | None) -> str | None:
    if not v:
        return None
    return v if re.search(r"[A-Za-z]", v) else f"{v} (unit not stated)"


def outfall_rows(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:
        if r.get("npdes_permit") == PERMIT and r.get("outfall_kind") == "cso" and r.get("lat") is not None \
                and r.get("coords_from") == "permitted_feature" \
                and not str(r.get("outfall_status") or "").upper().startswith("CLS"):
            out[outfall_number(r.get("outfall"))] = r
    return out


def make_to_records(registry: list[dict] | None = None):
    points = None

    def to_records(notices: list[dict]) -> list[dict]:
        nonlocal points
        if points is None:
            points = outfall_rows(registry if registry is not None else load_outfall_registry())
        by_start: dict[str, list[dict]] = {}
        for n in notices:
            if n.get("start"):
                by_start.setdefault(datetime.fromisoformat(n["start"]).strftime("%Y%m%dT%H%M"), []).append(n)
        recs = [to_record(k, v, points) for k, v in by_start.items()]
        recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
        return recs
    return to_records


def to_record(key: str, notices: list[dict], points: dict[str, dict]) -> dict:
    notices = sorted(notices, key=lambda n: (n["first_seen_at"], n["url"]))
    latest = notices[-1]
    st = datetime.fromisoformat(latest["start"])
    end = datetime.fromisoformat(latest["end"]) if latest.get("end") else None
    raw = {"time_zone": TZ_NAME, "state": "OH",
           "notices": [{"kind": n["kind"], "pdf": n["url"], "form_date": n.get("form_date"),
                        "initial_notice_sent": n.get("initial_notice_sent"), "start_as_written": n["start_as_written"],
                        "end_as_written": n.get("end_as_written"), "volume_as_written": n.get("volume_as_written"),
                        "_first_seen_at": n["first_seen_at"], "_last_seen_in_source": n["last_seen_at"]}
                       for n in notices],
           "outfall_info": latest.get("outfall_info"), "impacted_areas": latest.get("impacted_areas"),
           "impacted_yes_no": latest.get("impacted_yes_no") or {},
           "_last_seen_in_source": max(n["last_seen_at"] for n in notices),
           "time_note": "times as the form writes them (24-hour), read as Eastern time (America/New_York)"}
    if end is None and latest.get("end_as_written"):
        raw["end_as_written"] = latest["end_as_written"]
        raw["end_note"] = f"the form's end time is not used ({latest.get('end_problem')}): the end is not confirmed"
    if end is not None and end < st:
        raw["end_as_written"] = latest["end_as_written"]
        raw["end_note"] = ("the form's end is before its start (one of them may be mistyped): the end is not used, so it "
                           "is not confirmed")
        end = None
    if end:
        raw["ended_at_precision"] = "minute"
    elif not latest.get("end_as_written"):
        raw["end_note"] = "the form gives no end time: the end is not confirmed"
    num = latest.get("outfall_number")
    # the whole identifier, digits only: "17A" is not outfall 017 (review 2026-11-16 P1)
    o = points.get(outfall_number(num)) if num and re.fullmatch(r"\d{1,3}", num) else None
    raw["place_basis"] = (f"the form's outfall {latest['outfall_number']} is registry outfall {o['outfall']} of {PERMIT}"
                          if o else f"the form's outfall ({latest.get('outfall_number') or 'none given'}) is not an "
                          f"open CSO outfall of {PERMIT} with its own point in the registry: no outfall or point tied")
    gal, note = volume(latest.get("volume_as_written"))
    if note:
        raw["volume_note"] = note
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status="ended" if end else "unknown",
        discharger_name=DISCHARGER, npdes_permit=PERMIT, outfall_id=o["outfall"] if o else None,
        outfall_name=latest.get("outfall_info"), waterbody_text=latest.get("water"),
        lat=o["lat"] if o else None, lon=o["lon"] if o else None, coord_source="outfall_layer" if o else None,
        started_at=st.isoformat(), ended_at=end.isoformat() if end else None, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=raw["_last_seen_in_source"],
        material=MATERIAL, volume_gal=gal, volume_text=volume_text(latest.get("volume_as_written")),
        estimate_flag="estimated" if gal else "unknown", authority=CREDIT, advice_text=None,
        source_url=latest["url"], raw=raw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", help="a saved index page (with --texts and --out: no network)")
    ap.add_argument("--texts", help="JSON {pdf address: extracted text}")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    kw = {"credit": CREDIT, "extra_meta": no_start_date}
    if a.index:
        if not (a.texts and a.out):
            ap.error("--index needs --texts and --out")
        out = Path(a.out)
        get = PN.FileGet(INDEX_URL, Path(a.index).read_text(errors="replace"), json.loads(Path(a.texts).read_text()))
        return PN.run_feed(SOURCE_ID, INDEX_URL, LINK, parse, make_to_records(), out.with_suffix(".state.json"),
                           now_iso(), get=get, out=out, text_of=PN.file_text, **kw)
    return PN.run_feed(SOURCE_ID, INDEX_URL, LINK, parse, make_to_records(), STATE_PATH, now_iso(), **kw)


def no_start_date(held: dict) -> dict:
    """meta.no_start_date: the forms read that give a start time with no date (no record is made from them)."""
    return {"no_start_date": sorted(u for u, n in held.items() if not n.get("image_only") and not n.get("start"))}


if __name__ == "__main__":
    sys.exit(main())
