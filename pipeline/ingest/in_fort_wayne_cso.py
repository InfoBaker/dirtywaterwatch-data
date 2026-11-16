"""Fort Wayne City Utilities' weekly CSO summary -> data/build/events/in-fort-wayne-cso-notifications.json.

Source (register row IN:in-fort-wayne-cso-notifications; 327 IAC 5-2.1 and 40 CFR 122.38, the Great Lakes CSO public
notice rule: Fort Wayne's outfalls drain to the Maumee River and Lake Erie)
  The city's "CSO Notification" page, https://utilities.cityoffortwayne.org/sewer-system/cso-notifications (200 to
  GitHub's runner, barrier recheck 2026-11-16; a Cloudflare check answers 403 to this Mac). The page says the summary
  "contains information about combined sewer overflow events that may have occurred within the past 7-days including
  locations where overflows have occurred, times when the overflows began and ended and an estimate of the amount of
  sewage released", "updated each week on Wednesday". It links one document, the latest week's "CSO Past Seven Days
  Summary", a PDF made by the city's eRIS report builder (BIRT), at
  /wp-content/uploads/<YYYY>/<MM>/CSO-7-Day-Summary-v2-<YYYY>-<Mon>-<DD>.pdf. The PDF carries no person's details.
  Layout (read on the 35 weekly PDFs posted 2026-03-04 to 2026-11-12): one page, five blocks of up to nine outfall columns (39 outfall
  numbers as the city writes them: "60", "4", "002"), each outfall three cells "Start of CSO Event", "End of CSO Event",
  "Event Discharge (MG)", one row per day of the seven-day week. A week with no overflow carries the banner "NO
  OVERFLOWS OCCURRED IN THE LAST 7 DAYS" and empty cells. An overflow over several days is split into one row per day:
  "4:10 PM 11:59 PM", then "12:00 AM 11:59 PM", ..., then "12:00 AM 12:56 PM". Some weeks were edited by hand after the
  report was made (cells added in another font, drawn after the table): they are read like any other cell.

Reading the PDF (pdf_pieces; pypdf, pipeline/requirements.txt, imported lazily so the parser and its tests run without
  it): every text-show operation's own position (pypdf's layout-mode text state, one piece per Tj). pypdf's layout text
  merges a row's pieces drawn in one text object ("4/2/2026 12:00 AM 11:59 PM 62.359") and spaces them by an average
  character width, which moves the values by a third of a column: never used to place a value. The layout text is kept
  only to check that every time and volume on the page was placed (a count check).
  parse() places each piece by position: header rows ("Start of CSO", "End of CSO", "Discharge") give each outfall's
  three cells; the numbers above them name the outfalls; the dates name the rows. A piece that falls in no cell, an
  unknown word, a cell that is not a 12-hour time or a number, a row with only some of its three cells, an end before
  its start, blocks with different days, a banner beside values, or no banner and no values: the document is not read
  (unread, health false), never "no overflows".

Records (one per overflow; built again on every run from the days held)
  - Each day is taken from the newest document that covers it (by the PDF's own creation time): a revised week (the
    same address with new content, or a new address for the same days) replaces those days' rows, and the records
    are rebuilt, so a revision never duplicates a record. Documents read earlier stay in the state when they leave
    the page: past reports.
  - A row ending 11:59 PM followed by the same outfall's row starting 12:00 AM the next day is one overflow (the
    summary's day split). Its source_record_id is "<outfall as written>:<first start, local YYYYMMDDTHHMM>";
    started_at the first row's start, ended_at the last row's end (minute), volume the sum of the rows' million
    gallons (volume_text lists them). An overflow that runs to 11:59 PM on a day no document read covers the next day
    of (the newest week's last day) has no end yet: status unknown, ended_at null, raw.end_note ("end not
    confirmed"), until the next week is read. One that starts 12:00 AM on a day whose day before no document covers may
    have begun earlier: raw.start_note says so; its start is the row's as given.
  - A week whose document says "no overflows" is a read with no record; it stays in the state as evidence that the
    days were read (meta.weeks).
  - Times: the cells are local wall-clock times with no zone. Fort Wayne is in Allen County, Indiana, on Eastern time
    (zones.indiana_zone; the PDFs' own creation stamps carry -05:00 in winter and -04:00 in summer):
    America/Indiana/Indianapolis. A time in the spring-forward gap is not read (the document is unread); an hour that
    repeats when daylight time ends is read as its first occurrence. published_at the PDF's creation time (the
    document's own stamp; the page is updated on Wednesdays); reported_at null; fetched_at the read that last showed
    the document; raw.document the address.
  - Place: permit IN0032191 (City of Fort Wayne; data/dischargers.json in-city-of-fort-wayne). The receiving water is
    the one the city's permit names for the outfall (CITY_WATERS: the discharge authorization table of permit IN0032191
    as printed in the city's 2024 Great Lakes CSO annual notice; the weekly summary names none). The outfall is tied to
    the registry's row of that number only when the row is an open CSO outfall with its own point (IDEM's layer or EPA's
    permitted feature, never the plant's point) and the row's water is the city's: outfall_id and the registry's point
    (coord_source outfall_layer). Otherwise no outfall and no point (raw.place_basis says why).
  - Volume: million gallons as written; the page calls it "an estimate": estimate_flag estimated.
  - Indiana's monthly totals (in_echo_cso_monthly, EPA's DMRs) for the same outfalls are untouched: they are shown as
    the monthly mark and never added to the discharge counts (build/charts.py reported_totals; build/status.py
    EPA_MONTHLY_SOURCES), as Lakewood's dated records sit beside Ohio's monthly DMRs. A dated record here and the
    month's total there describe the same discharges; only the dated record is counted.

State: data/build/in-fort-wayne-cso-state.json (every document read and its rows; the archive). Do not delete it.
Failures: a failed request or a page with no summary link is a failed read (ok=False, the previous records kept, the
  state unchanged); a linked document that cannot be fetched or read is unread: the held records are written, the
  document is named in the error and health stays false until it reads (retried every run).
History: the page links only the latest week; earlier weeks stay at their addresses. --backfill asks each week's
  address from BACKFILL_FROM (the Wednesday, then the Thursday and the Tuesday), slowly, and reads what answers; a
  week that answers 404 on all three days is listed in meta.backfill_missing (not read, never "no overflows").
Run from pipeline/: python -m ingest.in_fort_wayne_cso [--backfill [--from 2025-01-01]]
  [--pieces saved.json ... --out events.json] (saved piece files from pdf_pieces, read as documents of this run)
Cadence: hourly with the refresh (Indiana is live); the city posts weekly.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, HEADERS, event, load_outfall_registry, now_iso, outfall_number, read_json, save_raw,
                    write_events, write_json)
from ingest.oh_cso_pdf_notices import existing

SOURCE_ID = "in-fort-wayne-cso-notifications"
URL = "https://utilities.cityoffortwayne.org/sewer-system/cso-notifications"
BASE = "https://utilities.cityoffortwayne.org/wp-content/uploads/"
LINK = re.compile(r"/CSO-7-Day-Summary[^/\"']*\.pdf$", re.I)
TZ_NAME = "America/Indiana/Indianapolis"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "IN0032191"
DISCHARGER = "City of Fort Wayne"
DISCHARGER_ID = "in-city-of-fort-wayne"
STATE_PATH = BUILD_DIR / "in-fort-wayne-cso-state.json"
CREDIT = "Fort Wayne City Utilities, CSO Past Seven Days Summary"
MATERIAL = "combined sewage and stormwater"
TITLE = "CSO Past Seven Days Summary"
BANNER = re.compile(r"NO\s+OVERFLOWS\s+OCCURRED\s+IN\s+THE\s+LAST\s+7\s+DAYS", re.I)
WORDS = {"Date", "Event", "(MG)", "Start of CSO", "End of CSO", "Discharge"}
TIME = re.compile(r"(\d{1,2}):(\d{2}) ([AP])M")
MG = re.compile(r"\d+(?:\.\d+)?")
DAY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
LABEL = re.compile(r"\d{1,3}[A-Z]?")
BACKFILL_FROM = "2025-01-01"

# The receiving water of each outfall as permit IN0032191 names it (discharge authorization table, printed in the
# city's "Great Lakes CSO Public Notification Annual Report 2024", pages 51-54, read 2026-11-16), by outfall number.
_SM, _SJ, _MA = "Saint Mary's River", "Saint Joseph River", "Maumee River"
CITY_WATERS = {
    "2": _MA, "3": "Wigman Drain", "4": _SM, "5": _SM, "7": _SM, "11": _SM, "12": _SM, "13": _SM, "17": _SM,
    "18": _SM, "20": _SM, "21": _SM, "23": _SM, "24": _SM, "25": _SM, "27": _SM, "28": _SM, "29": _SM, "32": _SM,
    "33": _SM, "36": "Spy Run Creek", "39": _MA, "44": _SJ, "45": _SJ, "48": _MA, "50": _MA, "51": _SJ, "52": _SJ,
    "54": "Natural Drain #4", "55": _MA, "56": _SM, "57": _MA, "60": "Unnamed Ditch to Maumee River",
    "61": "Baldwin Ditch", "62": "Baldwin Ditch", "64": "Unnamed Ditch to Maumee River", "68": _SJ, "80": _MA,
    "81": "Baldwin Ditch",
}
WATERS_BASIS = ("the receiving water permit IN0032191 names for the outfall (the city's 2024 Great Lakes CSO annual "
                "notice); the weekly summary names none")


class LayoutError(ValueError):
    """The page links no summary: a failed read, never "no overflows"."""


class SummaryError(ValueError):
    """A document whose content is not the summary this reader knows: unread, never "no overflows"."""


# ---------------------------------------------------------------- reading the PDF (runner only: needs pypdf)

def pdf_pieces(content: bytes) -> dict:
    """{"pieces": [[page, x, y, text], ...] one per text-show operation at its own position, "layout_text": pypdf's
    layout text (for the count check), "created": the PDF's creation time (ISO, or None)}. Uses pypdf's layout-mode
    text state (a module pypdf does not document): a pypdf without it raises ImportError, so the document is unread."""
    import pypdf                                    # pipeline/requirements.txt
    from pypdf.generic import ContentStream
    from pypdf._text_extraction._layout_mode import _fixed_width_page as fw
    from pypdf._text_extraction._layout_mode._text_state_manager import TextStateManager
    reader = pypdf.PdfReader(io.BytesIO(content))
    pieces, layout = [], []
    for pn, page in enumerate(reader.pages):
        fonts = page._layout_mode_fonts()
        ops = iter(ContentStream(page.get("/Contents").get_object(), page.pdf, "bytes").operations)
        mgr = TextStateManager()
        for operands, op in ops:
            if op in (b"BT", b"q"):
                _, tjs = fw.recurse_to_target_op(ops, mgr, b"ET" if op == b"BT" else b"Q", fonts, True)
                for t in tjs:
                    txt = getattr(t, "text", None)
                    txt = getattr(t, "txt", "") if txt is None else txt
                    if str(txt).strip():
                        pieces.append([pn, round(float(t.tx), 1), round(float(t.ty), 1), str(txt)])
            elif op == b"Tf":
                fw.set_font_operation(mgr, fonts, operands)
            else:
                mgr.set_state_param(op, operands)
        layout.append(page.extract_text(extraction_mode="layout") or "")
    return {"pieces": pieces, "layout_text": "\n".join(layout),
            "created": pdf_date((reader.metadata or {}).get("/CreationDate"))}


def pdf_date(v) -> str | None:
    """"D:20261112122354-05'00'" -> "2026-11-12T12:23:54-05:00"; None when absent or not that form."""
    m = re.fullmatch(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})([+-])(\d{2})'?(\d{2})'?", str(v or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s, sign, oh, om = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}{sign}{oh}:{om}"


# ---------------------------------------------------------------- parsing the pieces (no pypdf)

def _clock(v: str) -> tuple[int, int] | None:
    m = TIME.fullmatch(v)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if not 1 <= h <= 12 or mi > 59:
        return None
    return h % 12 + (12 if ap == "P" else 0), mi


def cell_text(parts: list[tuple[float, int, str]] | None) -> str:
    """A cell's pieces joined left to right with no spaces (a hand-edited cell is drawn a character or two at a time:
    "2: 3 3 P M"), then a time written "H:MM AM" and a number as it stands; anything else is returned as joined, for
    the checks to refuse."""
    v = "".join(t for _, _, t in sorted(parts or [])).replace(" ", "")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})([AP])M", v, re.I)
    return f"{int(m.group(1))}:{m.group(2)} {m.group(3).upper()}M" if m else v


def local(day: str, clock: str) -> datetime | None:
    """The local instant of a day ("2026-04-03") and a cell ("10:20 PM"); None for an unreadable time or one in the
    spring-forward gap."""
    c = _clock(clock)
    if c is None:
        return None
    d = date.fromisoformat(day)
    return existing(datetime(d.year, d.month, d.day, c[0], c[1], tzinfo=TZ))


def parse(doc: dict) -> dict:
    """{"days": [ISO dates], "outfalls": [as written], "rows": [{outfall, day, start, end, mg}], "no_overflows": bool}
    from one document's pieces (module docstring). Raises SummaryError for anything else."""
    pieces = [(int(p[0]), float(p[1]), float(p[2]), " ".join(str(p[3]).split())) for p in doc.get("pieces") or []]
    pieces = [p for p in pieces if p[3]]
    texts = [p[3] for p in pieces]
    if TITLE not in texts:
        raise SummaryError(f"no '{TITLE}' title: not the weekly summary")
    used = set()
    for i, p in enumerate(pieces):
        if p[3] == TITLE or BANNER.fullmatch(p[3]):
            used.add(i)
    banner = any(BANNER.fullmatch(t) for t in texts)
    # header rows: the y of each row of "Start of CSO" pieces, per page
    heads = sorted({(p[0], p[2]) for p in pieces if p[3] == "Start of CSO"}, key=lambda k: (k[0], -k[1]))
    if not heads:
        raise SummaryError("no 'Start of CSO' header")
    blocks, all_days, outfalls, rows = [], None, [], []
    for bi, (pg, hy) in enumerate(heads):
        def at(word, dy=0.0, tol=1.5):
            return sorted((p[1], i) for i, p in enumerate(pieces) if p[0] == pg and p[3] == word and abs(p[2] - hy - dy) <= tol)
        s, e = at("Start of CSO"), at("End of CSO")
        d = sorted((p[1], i) for i, p in enumerate(pieces)
                   if p[0] == pg and p[3] == "Discharge" and 0 <= p[2] - hy <= 2)
        if not (len(s) == len(e) == len(d)) or not s:
            raise SummaryError(f"block {bi + 1}: {len(s)} start, {len(e)} end and {len(d)} discharge headers")
        groups = []
        for k in range(len(s)):
            nxt = s[k + 1][0] if k + 1 < len(s) else d[k][0] + (d[k][0] - s[k][0]) + 40
            if not s[k][0] < e[k][0] < d[k][0] < nxt:
                raise SummaryError(f"block {bi + 1}: the headers of column {k + 1} are out of order")
            groups.append({"cells": [(s[k][0] - 10, e[k][0] - 6), (e[k][0] - 6, d[k][0] - 12), (d[k][0] - 12, nxt - 10)],
                           "centre": (s[k][0] + d[k][0] + 30) / 2, "label": None})
        for _, i in s + e + d:
            used.add(i)
        # the words under the outfall numbers
        for i, p in enumerate(pieces):
            if p[0] == pg and -9 <= p[2] - hy <= 9 and p[3] in WORDS:
                used.add(i)
        # outfall numbers: the band 12 to 24 points above the header row
        for i, p in enumerate(pieces):
            if p[0] != pg or not 12 <= p[2] - hy <= 24 or i in used:
                continue
            if not LABEL.fullmatch(p[3]):
                raise SummaryError(f"block {bi + 1}: '{p[3][:30]}' above the columns is not an outfall number")
            g = min(groups, key=lambda g: abs(g["centre"] - p[1]))
            if abs(g["centre"] - p[1]) > 40 or g["label"] is not None:
                raise SummaryError(f"block {bi + 1}: outfall number '{p[3]}' is not over one column")
            g["label"] = p[3]
            used.add(i)
        if any(g["label"] is None for g in groups):
            raise SummaryError(f"block {bi + 1}: a column has no outfall number")
        blocks.append((pg, hy, groups))
    # rows: each block's dates lie below its header and above the next block's
    for bi, (pg, hy, groups) in enumerate(blocks):
        below = blocks[bi + 1][1] + 24 if bi + 1 < len(blocks) and blocks[bi + 1][0] == pg else -1e9
        days = {}
        for i, p in enumerate(pieces):
            if p[0] == pg and below < p[2] < hy - 3 and DAY.fullmatch(p[3]):
                mo, dd, y = map(int, DAY.fullmatch(p[3]).groups())
                try:
                    days[p[2]] = date(y, mo, dd).isoformat()
                except ValueError:
                    raise SummaryError(f"date '{p[3]}' is not a day") from None
                used.add(i)
        ds = sorted(days.values())
        if not ds:
            raise SummaryError(f"block {bi + 1}: no dated row")
        if any(date.fromisoformat(b) - date.fromisoformat(a) != timedelta(days=1) for a, b in zip(ds, ds[1:])):
            raise SummaryError(f"block {bi + 1}: its days are not consecutive: {ds}")
        if all_days is None:
            all_days = ds
        elif ds != all_days:
            raise SummaryError(f"block {bi + 1} has days {ds[0]} to {ds[-1]}, not the first block's")
        cells = {}
        for i, p in enumerate(pieces):
            if i in used or p[0] != pg or not below < p[2] < hy - 3:
                continue
            row = [y for y in days if abs(y - p[2]) <= 3.5]
            if len(row) != 1:
                raise SummaryError(f"block {bi + 1}: '{p[3][:30]}' is on no dated row")
            hit = [(g["label"], c) for g in groups for c, (lo, hi) in enumerate(g["cells"]) if lo <= p[1] < hi]
            if len(hit) != 1:
                raise SummaryError(f"block {bi + 1}: '{p[3][:30]}' is in no column")
            key = (days[row[0]], hit[0][0], hit[0][1])
            cells.setdefault(key, []).append((p[1], i, p[3]))
            used.add(i)
        for g in groups:
            outfalls.append(g["label"])
            for day in ds:
                st, en, mg = (cell_text(cells.get((day, g["label"], c))) for c in range(3))
                if not (st or en or mg):
                    continue
                if not (st and en and mg):
                    raise SummaryError(f"outfall {g['label']} on {day}: start '{st}', end '{en}', volume '{mg}': a "
                                       "row with only some of its cells")
                a, b = local(day, st), local(day, en)
                if a is None or b is None:
                    raise SummaryError(f"outfall {g['label']} on {day}: time '{st}' or '{en}' is not a time of that day")
                if b < a:
                    raise SummaryError(f"outfall {g['label']} on {day}: end {en} before start {st}")
                if not MG.fullmatch(mg):
                    raise SummaryError(f"outfall {g['label']} on {day}: volume '{mg}' is not a number")
                rows.append({"outfall": g["label"], "day": day, "start": st, "end": en, "mg": mg})
    left = [pieces[i][3] for i in range(len(pieces)) if i not in used]
    if left:
        raise SummaryError(f"text the reader does not know: {', '.join(repr(t[:30]) for t in left[:4])}")
    if len(set(outfalls)) != len(outfalls):
        raise SummaryError("an outfall number appears twice")
    # completeness check against pypdf's own layout text: the same characters, so no piece was lost in reading
    lt = doc.get("layout_text")
    if lt is not None:
        from collections import Counter
        a = Counter(c for c in lt if not c.isspace())
        b = Counter(c for p in doc.get("pieces") or [] for c in str(p[3]) if not c.isspace())
        if a != b:
            diff = sorted(((a - b) + (b - a)).items())[:6]
            raise SummaryError(f"the page's text and the pieces read differ: {diff}")
    if banner and rows:
        raise SummaryError("the 'no overflows' banner stands beside overflow rows")
    if not banner and not rows:
        raise SummaryError("no overflow row and no 'no overflows' banner")
    return {"days": all_days, "outfalls": outfalls, "rows": rows, "no_overflows": banner}


# ---------------------------------------------------------------- state and records

def take(state: dict, url: str, doc: dict, parsed: dict, sha: str, now: str, via: str) -> str:
    """Keep one read document in the state; returns "new", "revised" or "same"."""
    docs = state.setdefault("docs", {})
    prev = docs.get(url)
    if prev and prev.get("sha256") == sha:
        prev["last_seen_at"] = now
        return "same"
    entry = {"url": url, "sha256": sha, "created": doc.get("created"), "read_at": now, "via": via,
             "first_seen_at": (prev or {}).get("first_seen_at") or now, "last_seen_at": now, **parsed}
    if prev:
        entry["replaces"] = (prev.get("replaces") or []) + [{"sha256": prev.get("sha256"), "created": prev.get("created"),
                                                             "read_at": prev.get("read_at")}]
    docs[url] = entry
    state.setdefault("unread", {}).pop(url, None)
    return "revised" if prev else "new"


def day_owners(docs: dict) -> dict[str, dict]:
    """{day: the document that rules it}: the newest by its own creation time, then the later read."""
    out = {}
    for d in docs.values():
        for day in d.get("days") or []:
            cur = out.get(day)
            if cur is None or (d.get("created") or "", d.get("read_at") or "") > (cur.get("created") or "", cur.get("read_at") or ""):
                out[day] = d
    return out


def outfall_points(rows: list[dict]) -> dict[str, dict]:
    """Fort Wayne's open CSO outfalls in the registry with their own point, by outfall number."""
    out = {}
    for r in rows:
        if r.get("npdes_permit") != PERMIT or r.get("outfall_kind") != "cso" or r.get("lat") is None:
            continue
        status, cf = str(r.get("outfall_status") or ""), str(r.get("coords_from") or "")
        if status.upper().startswith("CLS") or "facility" in cf.lower():
            continue
        if cf not in ("state outfall layer", "permitted_feature") and not cf.startswith("EPA permitted feature"):
            continue
        out[outfall_number(r.get("outfall"))] = r
    return out


def same_water(a: str | None, b: str | None) -> bool:
    def n(v):
        v = re.sub(r"[’'`.]", "", str(v or "").lower())
        v = re.sub(r"\bsaint\b", "st", v)
        return " ".join(v.split())
    return bool(a and b) and n(a) == n(b)


def tie(label: str, points: dict[str, dict]) -> tuple[dict | None, str]:
    num = outfall_number(label)
    water = CITY_WATERS.get(num)
    o = points.get(num) if re.fullmatch(r"\d{1,3}", label) else None
    if o is None:
        return None, (f"outfall {label} is not an open combined sewer outfall of {PERMIT} with its own point in the "
                      "registry: no outfall or point tied")
    if not water:
        return None, f"the permit names no receiving water for outfall {label}: no outfall or point tied"
    if not same_water(water, o.get("water_name")):
        return None, (f"the permit names {water} for outfall {label}; the registry's outfall {o['outfall']} is on "
                      f"{o.get('water_name') or 'no named water'}: no outfall or point tied")
    return o, f"outfall {label} is registry outfall {o['outfall']} of {PERMIT}, on {water} in both"


def overflows(docs: dict) -> list[dict]:
    """The overflows the held days give: rows chained across midnight (module docstring)."""
    owners = day_owners(docs)
    rows = []
    for day, d in owners.items():
        rows += [{**r, "doc": d} for r in d.get("rows") or [] if r["day"] == day]
    rows.sort(key=lambda r: (outfall_number(r["outfall"]), r["day"], local(r["day"], r["start"])))
    out = []
    for r in rows:
        prev = out[-1] if out else None
        nd = (date.fromisoformat(r["day"]) - timedelta(days=1)).isoformat()
        if (prev and outfall_number(prev["outfall"]) == outfall_number(r["outfall"]) and prev["rows"][-1]["day"] == nd
                and prev["rows"][-1]["end"] == "11:59 PM" and r["start"] == "12:00 AM"):
            prev["rows"].append(r)
            continue
        out.append({"outfall": r["outfall"], "rows": [r]})
    for o in out:
        first, last = o["rows"][0], o["rows"][-1]
        nxt = (date.fromisoformat(last["day"]) + timedelta(days=1)).isoformat()
        before = (date.fromisoformat(first["day"]) - timedelta(days=1)).isoformat()
        o["open_end"] = last["end"] == "11:59 PM" and nxt not in owners
        o["open_start"] = first["start"] == "12:00 AM" and before not in owners
    return out


def to_record(o: dict, points: dict[str, dict]) -> dict:
    first, last = o["rows"][0], o["rows"][-1]
    label = o["outfall"]
    st = local(first["day"], first["start"])
    en = None if o["open_end"] else local(last["day"], last["end"])
    tied, basis = tie(label, points)
    water = CITY_WATERS.get(outfall_number(label))
    total = sum(float(r["mg"]) for r in o["rows"])
    parts = [r["mg"] for r in o["rows"]]
    vol = f"{total:.3f} million gallons" + (f" (daily rows {' + '.join(parts)})" if len(parts) > 1 else "")
    if o["open_end"]:
        vol += " so far"
    docs = []
    for r in o["rows"]:
        if r["doc"]["url"] not in docs:
            docs.append(r["doc"]["url"])
    newest = max((r["doc"] for r in o["rows"]), key=lambda d: (d.get("created") or "", d.get("read_at") or ""))
    raw = {"outfall_as_written": label, "time_zone": TZ_NAME, "state": "IN", "documents": docs,
           "rows": [{"day": r["day"], "start": r["start"], "end": r["end"], "million_gallons": r["mg"]} for r in o["rows"]],
           "time_note": ("the summary writes local times with no zone; Fort Wayne (Allen County) is on Eastern time: "
                         f"read as {TZ_NAME}"),
           "place_basis": basis, "water_basis": WATERS_BASIS if water else None,
           "_first_seen_at": min(r["doc"].get("first_seen_at") or "" for r in o["rows"]),
           "_last_seen_in_source": max(r["doc"].get("last_seen_at") or "" for r in o["rows"]),
           "published_basis": "the summary PDF's own creation time; the city posts the week's summary on Wednesday"}
    if len(o["rows"]) > 1:
        raw["day_split_note"] = ("the summary splits an overflow at midnight (a row ending 11:59 PM, the next day's "
                                 "starting 12:00 AM): its rows are one overflow here")
    if o["open_start"]:
        raw["start_note"] = ("the first row starts at 12:00 AM on the first day the summaries read cover: the overflow "
                             "may have begun the day before; the start is the row's as given")
    if o["open_end"]:
        raw["end_note"] = ("the last row runs to 11:59 PM on the last day the summaries read cover: the overflow may "
                           "have continued; end not confirmed until the next week's summary is read")
    if en:
        raw["ended_at_precision"] = "minute"
    return event(
        source_id=SOURCE_ID, source_record_id=f"{label}:{st.strftime('%Y%m%dT%H%M')}", event_type="cso",
        status="unknown" if o["open_end"] else "ended",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=PERMIT,
        outfall_id=tied["outfall"] if tied else None, outfall_name=f"CSO outfall {label}", waterbody_text=water,
        lat=tied["lat"] if tied else None, lon=tied["lon"] if tied else None,
        coord_source="outfall_layer" if tied else None,
        started_at=st.isoformat(), ended_at=en.isoformat() if en else None, time_precision="minute",
        reported_at=None, published_at=newest.get("created"), source_updated_at=None,
        fetched_at=raw["_last_seen_in_source"] or now_iso(),
        material=MATERIAL, volume_gal=int(round(total * 1_000_000)), volume_text=vol, estimate_flag="estimated",
        authority=CREDIT, advice_text=None, source_url=newest["url"], raw=raw)


def build(state: dict, registry: list[dict] | None = None) -> list[dict]:
    points = outfall_points(registry if registry is not None else load_outfall_registry())
    recs = [to_record(o, points) for o in overflows(state.get("docs") or {})]
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs


def weeks_meta(state: dict) -> list[dict]:
    return sorted(({"url": d["url"], "from": (d.get("days") or [None])[0], "to": (d.get("days") or [None])[-1],
                    "rows": len(d.get("rows") or []), "no_overflows": d.get("no_overflows"), "created": d.get("created"),
                    "via": d.get("via")} for d in (state.get("docs") or {}).values()),
                  key=lambda w: w["from"] or "", reverse=True)


# ---------------------------------------------------------------- fetching

def index_links(page: str) -> list[str]:
    out = []
    for href in re.findall(r'href="([^"]+\.pdf)"', page, re.I):
        url = urljoin(URL, unescape(href))
        if LINK.search(url) and url not in out:
            out.append(url)
    return out


def backfill_urls(start: str, today: date) -> list[list[str]]:
    """Per week from start: the addresses to try in order (the Wednesday, then the Thursday and the Tuesday)."""
    d = date.fromisoformat(start)
    d += timedelta(days=(2 - d.weekday()) % 7)
    weeks = []
    while d <= today:
        tries = []
        for x in (d, d + timedelta(days=1), d - timedelta(days=1)):
            tries.append(f"{BASE}{x:%Y/%m}/CSO-7-Day-Summary-v2-{x:%Y-%b-%d}.pdf")
        weeks.append(tries)
        d += timedelta(days=7)
    return weeks


def read_doc(state: dict, url: str, content: bytes, now: str, via: str, pieces_of=pdf_pieces) -> str:
    """Read one document into the state; returns "new", "revised", "same" or "unread" (reason in state.unread)."""
    sha = hashlib.sha256(content).hexdigest()
    doc = None
    held = (state.get("docs") or {}).get(url)
    if held and held.get("sha256") == sha:
        held["last_seen_at"] = now
        state.setdefault("unread", {}).pop(url, None)
        return "same"
    try:
        doc = doc if doc is not None else pieces_of(content)
        parsed = parse(doc)
    except (SummaryError, ValueError, ImportError, AttributeError, TypeError, KeyError) as e:
        state.setdefault("unread", {})[url] = f"{type(e).__name__}: {str(e)[:160]}"
        return "unread"
    return take(state, url, doc, parsed, sha, now, via)


def _get(url: str):
    return requests.get(url, headers=HEADERS, timeout=(20, 90))


def run(now: str, state_path: Path, out: Path | None = None, get=_get, backfill: bool = False,
        since: str = BACKFILL_FROM, today: date | None = None, sleep=time.sleep, pieces_of=pdf_pieces,
        registry: list[dict] | None = None, save: bool = True) -> int:
    """One run (module docstring); returns the exit code. get(url) returns a response (status_code, content, text)."""
    try:
        r = get(URL)
        r.raise_for_status()
        links = index_links(r.text)
        if not links:
            raise LayoutError("no CSO-7-Day-Summary PDF link on the page")
    except (requests.RequestException, LayoutError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    state = read_json(state_path, {}) or {}
    unread = state.setdefault("unread", {})
    counts = {"new": 0, "revised": 0, "same": 0, "unread": 0, "gone": 0}

    def fetch(url: str, via: str) -> int | None:
        """Read one address; returns its HTTP status (None when the request failed)."""
        try:
            resp = get(url)
            if resp.status_code == 429:
                sleep(90)
                resp = get(url)
        except requests.RequestException as e:
            unread[url] = f"{type(e).__name__}: {str(e)[:160]}"
            counts["unread"] += 1
            return None
        if resp.status_code != 200:
            return resp.status_code
        counts[read_doc(state, url, resp.content, now, via, pieces_of=pieces_of)] += 1
        return 200

    # the page's documents, then every document still unread from an earlier run (the PDFs stay at their addresses)
    for u in links + [u for u in list(unread) if u not in links]:
        code = fetch(u, "page" if u in links else (state.get("docs", {}).get(u) or {}).get("via") or "retry")
        if code not in (200, None):
            if code == 404 and u not in links:
                state.setdefault("left_unread", {})[u] = {"why": unread.pop(u, ""), "seen_gone_at": now}
                counts["gone"] += 1
            else:
                unread[u] = f"HTTP {code}"
                counts["unread"] += 1
    if backfill:
        missing = []
        for tries in backfill_urls(since, today or datetime.now(TZ).date()):
            if any(t in (state.get("docs") or {}) or t in unread for t in tries):
                continue
            for t in tries:
                sleep(2)
                code = fetch(t, "backfill")
                if code == 404:
                    continue
                if code not in (200, None):
                    unread[t] = f"HTTP {code}"
                    counts["unread"] += 1
                break
            else:
                missing.append(tries[0].rsplit("/", 1)[-1])
        state["backfill_missing"] = missing
    state["last_read"] = {"at": now, "listed": len(links), **counts}
    write_json(state_path, state)
    if save and (counts["new"] or counts["revised"]):
        save_raw(SOURCE_ID, json.dumps({u: {k: d.get(k) for k in ("days", "rows", "no_overflows", "created")}
                                        for u, d in state["docs"].items() if d.get("read_at") == now}), "json")
    recs = build(state, registry)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "credit": CREDIT, "listed": links, "weeks": weeks_meta(state),
            "backfill_missing": state.get("backfill_missing") or [], "left_unread": sorted(state.get("left_unread") or {}),
            "covers_permits": [PERMIT], "time_zone": TZ_NAME}
    if unread:
        meta["unread"] = dict(unread)
        write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, path=out,
                     error="documents not read: " + "; ".join(f"{u.rsplit('/', 1)[-1]}: {w}" for u, w in unread.items()))
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; {len(unread)} documents not read", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records from {len(state.get('docs') or {})} weekly summaries -> {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="also ask every week's address from --from")
    ap.add_argument("--from", dest="since", default=BACKFILL_FROM)
    ap.add_argument("--pieces", action="append",
                    help="saved pdf_pieces files (JSON), read in place of the PDFs the page links (needs --out)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.pieces and not a.out:
        ap.error("--pieces needs --out")
    out = Path(a.out) if a.out else None
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    if a.pieces:
        saved = {Path(p).resolve().as_uri(): json.loads(Path(p).read_text()) for p in a.pieces}
        page = "".join(f'<a href="{u}.pdf">x</a>' for u in saved)

        class R:
            def __init__(self, status, text="", content=b""):
                self.status_code, self.text, self.content = status, text, content

            def raise_for_status(self):
                if self.status_code != 200:
                    raise requests.HTTPError(str(self.status_code))

        def get(u):
            if u == URL:
                return R(200, page.replace(".pdf", "/CSO-7-Day-Summary.pdf"))
            key = u.rsplit("/CSO-7-Day-Summary.pdf", 1)[0]
            return R(200, content=json.dumps(saved[key]).encode()) if key in saved else R(404)
        return run(now_iso(), state_path, out, get=get, pieces_of=lambda c: json.loads(c), save=False)
    return run(now_iso(), state_path, out, backfill=a.backfill, since=a.since)


if __name__ == "__main__":
    sys.exit(main())
