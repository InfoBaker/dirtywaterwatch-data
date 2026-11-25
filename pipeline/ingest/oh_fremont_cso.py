"""City of Fremont CSO notifications (PDF) -> data/build/events/oh-fremont-cso-notices.json.

Public-record policy: downloaded source text is retained, including published names, contacts and addresses.
Structured event classification still uses the documented source fields. Requested removals apply at export.


Source (registry oh-fremont-cso-notices; 40 CFR 122.38, the Great Lakes CSO public notice rule)
  The Water Reclamation Center page, https://www.fremontohio.org/departments/water-reclamation-center/ (200 to this
  machine and GitHub's runner, 2026-11-16), links one PDF per notice under wp-content/uploads ("8-9-26-CSO-
  Notification.pdf", "3-31-2026-SUPPLEMENTAL-NOTIFICATION-OF-COMBINED-SEWER-OVERFLOW-EVENT-Copy.pdf", ...): ten in
  2026 on 2026-11-16, from 2026-03-11 to 2026-08-09, all headed "Supplemental NOTIFICATION OF COMBINED SEWER OVERFLOW
  EVENT". Each gives "1. Receiving water body" (Sandusky River), "2. Location of the discharges" ("Downtown Fremont to
  discharge channel of Fremont WRC."), "3. Point of contact" (a staff e-mail and telephones: never read or saved),
  then one row: Date and Time CSO Started, Date and Time CSO Ended, Approximate Volume of CSO (MG). The index's other
  PDFs (annual reports, the notification plan, the storm-water permit) are not notices and are not read; a notice
  link is a PDF whose name says CSO, or NOTIFICATION with COMBINED SEWER, and not annual, report or plan.
  One notice (CSO-July21-2026.pdf) is a scanned image with no text: it stays unread, and health false, while listed.
  The row's cells are read one by one (start; end and volume when given); a cell that is not what its column holds
  fails the notice.

Records
  - One cso record per overflow: source_record_id the start, local YYYYMMDDTHHMM. An initial notice of the same
    start would be the same record, revised by the supplemental one (none posted so far).
  - started_at and ended_at as the row writes them ("8/9/2026 9:17PM"), minute, America/New_York (the PDFs state no
    zone; Fremont keeps Eastern time; a repeated fall-back hour is read as its first occurrence). An end before the
    start (the notice of 2026-04-22 gives 5:50PM to 10:52AM the same day) is not used: ended_at null, status unknown,
    raw.end_as_written keeps it and raw.end_note says why. No end is ever invented.
  - volume_gal from the row's million gallons, estimate_flag estimated (the column says "Approximate"), volume_text
    as written with the unit.
  - Place: permit OH0025291 (Fremont Water Reclamation Center; data/dischargers.json). The notices name no outfall:
    no outfall or point is tied (the registry has 14 CSO outfalls on the permit); waterbody_text the receiving water
    as named; raw.location the location line.
  - Times: published_at, reported_at and source_updated_at null (the PDFs give no date of posting; the upload month
    in the address is not a date of the notice); fetched_at and raw._last_seen_in_source the last read that listed
    the notice; raw.pdf the notice's address (source_url too).
  Privacy: only the fields above are parsed; the point-of-contact line and the comments are never read.

State: data/build/oh-fremont-cso-state.json (oh_cso_pdf_notices: every notice read, by address). Do not delete it.
Failures, unread notices and image-only PDFs: oh_cso_pdf_notices.run_feed.
History: the index lists every 2026 notice; older years are summarised only in annual reports. No --backfill.
Run from pipeline/: python -m ingest.oh_fremont_cso [--index saved.html --texts texts.json --out events.json]
  (texts.json: {pdf address: extracted text}, for a run without the network)
Cadence: hourly with the refresh (Ohio is live); only new PDFs are fetched.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from common import BUILD_DIR, event, now_iso
from ingest import oh_cso_pdf_notices as PN

SOURCE_ID = "oh-fremont-cso-notices"
INDEX_URL = "https://www.fremontohio.org/departments/water-reclamation-center/"
LINK = re.compile(r"/wp-content/uploads/\d{4}/\d{2}/(?!.*(?:annual|report|plan|np-rev|ms4|sso))"
                  r"(?=[^/]*(?:cso|notification[^/]*combined-sewer))[^/]+\.pdf$", re.I)
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "OH0025291"
DISCHARGER = "Fremont Water Reclamation Center"
STATE_PATH = BUILD_DIR / "oh-fremont-cso-state.json"
CREDIT = "City of Fremont, CSO notification"
MATERIAL = "combined sewage and stormwater"
DT = r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\s*([AP])\.?M\.?"
ROW = re.compile(DT + r"(?:\s+" + DT + r")?(?:\s+(\d*\.?\d+))?", re.I)


def local(d: str, hm: str, ap: str) -> datetime | None:
    try:
        mo, dd, y = (int(x) for x in d.split("/"))
        h, mi = (int(x) for x in hm.split(":"))
        if not 1 <= h <= 12:
            return None
        return PN.existing(datetime(y, mo, dd, h % 12 + (12 if ap.upper() == "P" else 0), mi, tzinfo=TZ))
    except ValueError:
        return None


CELL_DT = re.compile(DT + r"$", re.I)
CELL_VOL = re.compile(r"\d*\.?\d+$")


def row_cells(text: str) -> list[str]:
    """The cells of the notice's one data row: the first line after the column headings that holds anything, split
    on runs of two or more spaces (pypdf's layout text)."""
    raw = text.splitlines()
    i = next((k for k, ln in enumerate(raw) if re.search(r"of CSO \(MG\)", ln, re.I)), None)
    if i is None:
        raise PN.NoticeError("the notice's column headings were not found")
    for ln in raw[i + 1:]:
        if ln.strip():
            if re.match(r"\s*Comments\s*:", ln, re.I):
                break
            return [c.strip() for c in re.split(r"\s{2,}", ln.strip()) if c.strip()]
    raise PN.NoticeError("the notice's row is empty")


def field(ls: list[str], label: str) -> str | None:
    for ln in ls:
        m = re.search(label + r"\s*:\s*(.*)$", ln, re.I)
        if m:
            return m.group(1).strip() or None
    return None


def parse(text: str) -> dict:
    """The fields of one notice's text; NoticeError when it is not Fremont's form."""
    ls = PN.lines(text)
    joined = " ".join(ls)
    if not re.search(r"NOTIFICATION OF COMBINED SEWER\s+OVERFLOW", joined, re.I) or \
            not re.search(r"Date and Time CSO", joined, re.I):
        raise PN.NoticeError("not Fremont's CSO notification form")
    kind = "supplemental" if re.match(r"\s*Supplemental\b", joined, re.I) else \
        "initial" if re.match(r"\s*Initial\b", joined, re.I) else "notice"
    # each cell is read on its own: start, then end and volume when given; a cell that is not what its column
    # holds fails the notice (an unreadable end never becomes a volume; review 2026-11-16 P1)
    cells = row_cells(text)
    if not 1 <= len(cells) <= 3:
        raise PN.NoticeError(f"the row has {len(cells)} cells")
    ms = CELL_DT.match(cells[0])
    if not ms:
        raise PN.NoticeError(f"start cell '{cells[0][:30]}' not read")
    me = CELL_DT.match(cells[1]) if len(cells) >= 2 and not CELL_VOL.match(cells[1]) else None
    rest = cells[1:]
    if me:
        rest = cells[2:]
    if len(rest) > 1 or (rest and not CELL_VOL.match(rest[0])) or (len(cells) == 3 and not me):
        raise PN.NoticeError(f"row cells {cells!r} not read")
    g = ms.groups() + (me.groups() if me else (None, None, None)) + ((rest[0],) if rest else (None,))
    st = local(g[0], g[1], g[2])
    if st is None:
        raise PN.NoticeError(f"start '{cells[0][:30]}' not read")
    end = local(g[3], g[4], g[5]) if g[3] else None
    if g[3] and end is None:
        raise PN.NoticeError(f"end '{cells[1][:30]}' not read")
    return {"source_text": text, "kind": kind, "start": st.isoformat(), "start_as_written": f"{g[0]} {g[1]}{g[2]}M",
            "end": end.isoformat() if end else None,
            "end_as_written": f"{g[3]} {g[4]}{g[5]}M" if g[3] else None,
            "volume_mg": g[6], "water": field(ls, r"Receiving water body"),
            "location": field(ls, r"Location of the discharges")}


def to_records(notices: list[dict]) -> list[dict]:
    by_start: dict[str, list[dict]] = {}
    for n in notices:
        by_start.setdefault(datetime.fromisoformat(n["start"]).strftime("%Y%m%dT%H%M"), []).append(n)
    recs = [to_record(k, v) for k, v in by_start.items()]
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    return recs


def to_record(key: str, notices: list[dict]) -> dict:
    notices = sorted(notices, key=lambda n: (n["kind"] != "initial", n["first_seen_at"], n["url"]))
    latest = notices[-1]
    st = datetime.fromisoformat(latest["start"])
    end = datetime.fromisoformat(latest["end"]) if latest.get("end") else None
    raw = {"time_zone": TZ_NAME, "state": "OH", "location": latest.get("location"),
           "notices": [{"source_text": n.get("source_text"), "kind": n["kind"], "pdf": n["url"], "start_as_written": n["start_as_written"],
                        "end_as_written": n.get("end_as_written"), "volume_mg_as_written": n.get("volume_mg"),
                        "_first_seen_at": n["first_seen_at"], "_last_seen_in_source": n["last_seen_at"]}
                       for n in notices],
           "_last_seen_in_source": max(n["last_seen_at"] for n in notices),
           "place_basis": (f"the notices name the receiving water and 'Downtown Fremont', not an outfall number; "
                           f"no outfall of permit {PERMIT} is tied"),
           "time_note": "times as the notice writes them, read as Eastern time (America/New_York): the PDF states no zone"}
    if end is not None and end < st:
        raw["end_as_written"] = latest.get("end_as_written")
        raw["end_note"] = "the notice's end is before its start: it is not used, so the end is not confirmed"
        end = None
    if end:
        raw["ended_at_precision"] = "minute"
    try:
        mg = float(latest["volume_mg"]) if latest.get("volume_mg") else None
    except ValueError:
        mg = None
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status="ended" if end else "unknown",
        discharger_name=DISCHARGER, npdes_permit=PERMIT, outfall_id=None, outfall_name=None,
        waterbody_text=latest.get("water"), lat=None, lon=None, coord_source=None,
        started_at=st.isoformat(), ended_at=end.isoformat() if end else None, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=raw["_last_seen_in_source"],
        material=MATERIAL, volume_gal=int(round(mg * 1_000_000)) if mg else None,
        volume_text=f"{latest['volume_mg']} million gallons (approximate)" if mg else None,
        estimate_flag="estimated" if mg else "unknown", authority=CREDIT, advice_text=None,
        source_url=latest["url"], raw=raw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", help="a saved index page (with --texts and --out: no network)")
    ap.add_argument("--texts", help="JSON {pdf address: extracted text}")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.index:
        if not (a.texts and a.out):
            ap.error("--index needs --texts and --out")
        out = Path(a.out)
        get = PN.FileGet(INDEX_URL, Path(a.index).read_text(errors="replace"), json.loads(Path(a.texts).read_text()))
        return PN.run_feed(SOURCE_ID, INDEX_URL, LINK, parse, to_records, out.with_suffix(".state.json"), now_iso(),
                           get=get, out=out, credit=CREDIT, text_of=PN.file_text)
    return PN.run_feed(SOURCE_ID, INDEX_URL, LINK, parse, to_records, STATE_PATH, now_iso(), credit=CREDIT)


if __name__ == "__main__":
    sys.exit(main())
