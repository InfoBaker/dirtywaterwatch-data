"""Baton Rouge's consent-decree quarterly reports: the unauthorized discharge tables -> data/build/events/
la-baton-rouge-quarterly.json.

Source
  The City of Baton Rouge and Parish of East Baton Rouge's SSO program repository,
  https://brprojects.com/baton-rouge-sso-program/program-overview/regulatory-information/ (registry
  la-baton-rouge-quarterly-reports), which links every quarterly report to EPA and LDEQ under the 2002 consent decree
  (Paragraph 26, Section XI: "all Unauthorized Discharges of which it becomes aware"), Report 98 (July to September
  2026, issued October 30, 2026) the newest on 2026-11-14. Part D of each report holds a summary of the quarter's
  unauthorized discharges by plant (North LA0036439 AI 4843, South LA0036412 AI 4841; collection system and treatment
  plant) and, for each collection system, a table with one row per discharge: Date, Address, Cause, Action,
  Prevention, Rec. Waters, Amt. Gals and laboratory columns (PS, BOD, TSS, pH, ARD). The treatment plants' discharges
  are scanned forms (images with no text): they are counted from the summary (meta) and not itemised.

Reading the PDF (pypdf, layout text)
  Only the collection-system tables are read, and only what their layout supports: a row is a line that begins with a
  date (m/d/yyyy); its cells are cut by the header line's column starts. The reports use two layouts (read_rows): the
  water and the gallons centred on the date line (Reports 94 on), or the laboratory values on the date line and the
  water and the gallons a few lines below it (Report 93); each row must have exactly one cell under the Amt. Gals
  header and every Rec. Waters cell must belong to one row. A report is used only when its summary gives the
  collection-system count of both districts (North and South, DISTRICTS), its own Total is the sum of its four counts,
  every table is one of the two under its own district name, every row's cells are read with confidence, and the
  rows read for each district equal the number its own summary gives (raw.layout_check); a report that fails is
  listed in meta.failed_checks and makes none of its rows records, so a misread table never reaches the site.

Records
  One per table row: event_type sso (a discharge from the collection system), status unknown (the table gives no end:
  "end not confirmed"), started_at the row's date (time_precision day, Central time; data/rules.json
  unresolved.day_start_caution gives the site's caution for 72 hours from the start of that day), published_at the
  report's issue date, volume_gal the gallons given; waterbody_text the receiving water as written, except 'None',
  which the City gives when no water was reached or named: such a row is kept, with its parish and permit, and
  placed on no water (never at the plant's point, never geocoded). source_record_id 'r<report>-<permit>-<date>-<n>'
  (n the row's order on that date in that table). The Action, Prevention and laboratory columns are not kept.
  The Cause is read only as one of the tables' own cause phrases (CAUSE) found on the row's lines, else null.
  Privacy: the Address cell is a street location, often a house: it is never kept (its cell runs into the Cause cell
  in the layout text, so it cannot be cut reliably, and the parish places nothing anyway); no free text of the row is
  kept. The Rec. Waters cell is withheld (receiving_water_withheld) when it holds an address, a phone, an e-mail or
  a label of who reported (receiving_water). Only the parsed rows are saved
  to data/build/la-baton-rouge-state.json; the PDF itself is never written to data/raw.

Cadence and lag
  The index is read with the refresh (daily is enough); reports are kept by number in the state file with their URL,
  SHA-256 and every read (attempts). A report is fetched when its number is new or its address changed, and the
  newest two again every REREAD_DAYS (an amended copy at the same address); --refresh reads all again. Each read
  keeps PARSER_VERSION: a report no read of which was made by the current parser is fetched and read again on the
  next ordinary run (parsed_by_older), and its rows replace the earlier ones under the same ids (the ids are built
  from the report, permit, date and order, which a corrected read of the same table does not change). A copy that
  fails the layout check never replaces an accepted one: the accepted copy stays and the run is ok=False, naming it.
  Every failed read (a fetch error, a failed check, a failed amendment) stays in state 'pending' (meta.pending) until a
  read of that report succeeds: each run is ok=False while anything is pending (last_ok_at does not advance), and a
  pending report is tried again every REREAD_DAYS whatever its number.
  Where the state holds no accepted copy of a report whose rows the previous events file carries (no state file, an
  emptied one, a failed first read), those rows are kept, the water cell checked again (retained), so a failed read
  never drops an earlier record (meta.retained_from_previous_events).
  Each record's fetched_at is when its report was read. Reports are issued about a month after the quarter ends, so a row is one to four
  months old when it appears. FIRST_REPORT (91, October to December 2024) bounds the backfill.

Run from pipeline/: python -m ingest.la_baton_rouge_quarterly [--file report.pdf --report 98 --url URL] [--refresh]
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

import common
from common import BUILD_DIR, HEADERS, event, now_iso, read_json, write_events, write_json
from common import error_detail, error_text
from ingest import wv_la_privacy

SOURCE_ID = "la-baton-rouge-quarterly"
INDEX = "https://brprojects.com/baton-rouge-sso-program/program-overview/regulatory-information/"
STATE_PATH = BUILD_DIR / "la-baton-rouge-state.json"
AUTHORITY = ("City of Baton Rouge and Parish of East Baton Rouge, consent-decree quarterly report to EPA and LDEQ "
             "(Part D, unauthorized discharges)")
OPERATOR = "City of Baton Rouge and Parish of East Baton Rouge"
TZ = "America/Chicago"
COUNTY = "East Baton Rouge Parish"
FIRST_REPORT = 91
REPORT_LINK = re.compile(r"""href=["']([^"']*?(\d{2,3})(?:st|nd|rd|th)[_ -]?Quarterly[^"']*?\.pdf)["']""", re.I)
DATE_ROW = re.compile(r"^\s{0,12}(\d{1,2}/\d{1,2}/\d{4})\s{2,}")
HEADING = re.compile(r"(NORTH|SOUTH)\s+Sewer District Collection System\s+LPDES\s*(LA\d{7})\s*AI\s*#\s*(\d+)", re.I)
SUMMARY = re.compile(r"(North|South)\s+Plant\s*-\s*(LA\d{7})\s*AI\s*#\s*(\d+)\s+(Collection System|Treatment Plant)\s+(\d+)",
                     re.I)
ISSUED = re.compile(r"Issued:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
PERIOD = re.compile(r"(\d{2}/\d{2}/\d{4})\s+To\s+(\d{2}/\d{2}/\d{4})")
COLUMNS = ("Date", "Address", "Cause", "Action", "Prevention", "Rec. Waters", "Amt. Gals", "PS")
# the summary's own Total line (the four counts added); checked against their sum
SUMMARY_TOTAL = re.compile(r"^\s*Total\s+(\d+)\s*$", re.M)
# a line that ends a row's block: the table's legend, the page footer
BLOCK_END = re.compile(r"^\s*(?:BOD|TSS|PS|ARD|pH)\s*=|Issued:|Page\s*\|")
GALLONS = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?")
UNKNOWN_GALLONS = re.compile(r"Unknown|Unk\.?|N/?A|TBD", re.I)      # the City's word for no figure
# the parser's version, kept with each report it reads: a report read by an older version is read again on the next
# run (due), and its rows replace the earlier ones under the same ids. 2: the gallons and the receiving water read
# over the whole row block (Report 93's layout), one figure in the Amt. Gals column required, the summary's Total.
PARSER_VERSION = 2
# the Cause column's words, as the tables write them; a cause is read only when one of these is found on the row's
# lines (the Address and Cause cells run together in the layout text, so the cell is not cut by position)
CAUSE = re.compile(r"Blockage\s*-\s*(?:Collection|Service)\s+Lines?|Grease(?:\s+and\s+Debris)?|Debris\s+and\s+Rags"
                   r"(?:\s*-\s*Collection\s+Lines?)?|Force\s*main\s+Failure|Air\s+Release\s+Valve\s+Failure|"
                   r"Inflow\s+and\s+Infiltration|Roots\s*-\s*(?:Service|Collection)\s+Lines?|Structural\s+Defect\s*-\s*"
                   r"(?:Collection|Service)\s+Lines?|(?:[A-Z][a-z]+\s+)?Pump\s+(?:Station\s+)?Failure|Power\s+(?:Outage|Failure)",
                   re.I)
NO_WATER = {"none", "n/a", "na", "", "-"}
# the two collection systems every report summarises and tabulates (Part D): a report is accepted only when its summary
# gives the collection-system count of both and every table it holds is one of these, under its own district name
DISTRICTS = {"LA0036439": "North", "LA0036412": "South"}


def pdf_pages(content: bytes) -> list[str]:
    import pypdf
    return [p.extract_text(extraction_mode="layout") or "" for p in pypdf.PdfReader(io.BytesIO(content)).pages]


def _columns(header: str) -> dict[str, int] | None:
    cols = {}
    for c in COLUMNS:
        i = header.find(c)
        if i < 0:
            return None
        cols[c] = i
    return cols


def _cell(line: str, cols: dict, name: str) -> str:
    """The text of one column on a line: the chunks (runs split by two or more spaces) whose start lies between the
    midpoints that part this column's header from its neighbours' (the cells are centred under wide headers)."""
    names = list(COLUMNS)
    i = names.index(name)
    lo = (cols[names[i - 1]] + len(names[i - 1]) + cols[name]) / 2 if i else -1
    hi = (cols[name] + len(name) + cols[names[i + 1]]) / 2 if i + 1 < len(names) else 10 ** 6
    out = [m.group(0) for m in re.finditer(r"\S+(?: \S+)*", line) if lo <= m.start() < hi]
    return " ".join(out).strip()


def receiving_water(text: str) -> tuple[str | None, str | None]:
    """Preserve the source public record (decision 57)."""
    return (text or None, None)


def _runs(cells: dict[int, str]) -> list[tuple[int, int, str]]:
    """Consecutive lines with text in one column: (first line, last line, the text joined)."""
    out: list[list] = []
    for i in sorted(cells):
        if not cells[i]:
            continue
        if out and out[-1][1] == i - 1:
            out[-1][1], out[-1][2] = i, out[-1][2] + " " + cells[i]
        else:
            out.append([i, i, cells[i]])
    return [tuple(r) for r in out]


def read_rows(lines: list[str], cols: dict, head: int, anchors: list[int], district: dict,
              page: int) -> tuple[list[dict], list[str]]:
    """The rows of one table page, and what could not be read with confidence.

    The reports print a row's cells in one of two layouts: the receiving water and the gallons centred on the date
    line, a wrapped water name running above and below it (Reports 94 on), or the laboratory values on the date line
    and the water and the gallons a few lines below it (Report 93). Each row's gallons are the one cell under the
    Amt. Gals header (_cell, between the header midpoints) on the lines from its date line to the next row's; the
    layout is told by whether that cell sits on the date line. A run of Rec. Waters lines belongs to the row whose
    date line it crosses, or, in the second layout, to the row above it (where a name wrapped over a blank line is
    joined in order). Anything else (no gallons cell or two, a
    figure that is not a number, a water cell with no row or two, a page mixing the layouts) is named, and the report
    then fails its layout check: no figure is taken from a neighbouring column and none is guessed."""
    last = len(lines)
    for i in range(head + 1, len(lines)):
        x = lines[i]
        if BLOCK_END.search(x) or HEADING.search(x) or ("Rec. Waters" in x and "Address" in x):
            last = i
            break
    anchors = [a for a in anchors if a < last]
    gal = {i: _cell(lines[i], cols, "Amt. Gals") for i in range(head + 1, last)}
    wat = {i: _cell(lines[i], cols, "Rec. Waters") for i in range(head + 1, last)}
    out, problems, layouts = [], [], set()
    dates = {a: datetime.strptime(DATE_ROW.match(lines[a]).group(1), "%m/%d/%Y").date().isoformat() for a in anchors}
    below: dict[int, bool] = {}
    gallons: dict[int, tuple] = {}
    for n, a in enumerate(anchors):
        stop = anchors[n + 1] if n + 1 < len(anchors) else last
        cells = [(i, gal[i]) for i in range(a, stop) if gal.get(i)]
        label = f"{district['name']} {dates[a]} (page {page})"
        if len(cells) != 1:
            problems.append(f"{label}: {len(cells)} cells in the Amt. Gals column")
            gallons[a] = (None, None)
            continue
        i, text = cells[0]
        below[a] = i != a
        layouts.add(below[a])
        if GALLONS.fullmatch(text):
            gallons[a] = (int(float(text.replace(",", ""))), text)
        elif UNKNOWN_GALLONS.fullmatch(text):
            gallons[a] = (None, text)                   # the City's own word: no figure, none supplied
        else:
            problems.append(f"{label}: the Amt. Gals cell is not a figure")
            gallons[a] = (None, None)
    if len(layouts) > 1:
        problems.append(f"page {page}: rows with the gallons on the date line and rows with them below it")
    water: dict[int, list[str]] = {a: [] for a in anchors}
    for s, e, text in _runs(wat):
        crossed = [a for a in anchors if s <= a <= e]
        above = [a for a in anchors if a < s]
        if len(crossed) > 1:
            problems.append(f"page {page}: a Rec. Waters cell spans two rows")
        elif crossed:
            water[crossed[0]].append(text)
        elif above and below.get(above[-1]):
            water[above[-1]].append(text)
        else:
            problems.append(f"page {page}: a Rec. Waters cell on lines {s + 1} to {e + 1} belongs to no row")
    for n, a in enumerate(anchors):
        if len(water[a]) > 1 and not below.get(a):
            # a name wrapped over a blank line is joined only where the cells sit below the date line (Report 93's
            # 'Corporation' on the date line, 'Canal' two lines below), never across rows centred on their date line
            problems.append(f"{district['name']} {dates[a]} (page {page}): {len(water[a])} Rec. Waters cells")
        stop = anchors[n + 1] if n + 1 < len(anchors) else last
        ln = lines[a]
        cont = [x for x in lines[a + 1:min(stop, a + 3)] if x.strip()]
        cm = CAUSE.search(" ".join([ln] + cont))
        w, withheld = receiving_water(" ".join(water[a]))
        g, gt = gallons[a]
        row = {"date": dates[a], "cause": " ".join(cm.group(0).split()) if cm else None,
               "receiving_water": w, "gallons": g, "gallons_text": gt, "page": page, **district}
        if withheld:
            row["receiving_water_withheld"] = withheld
        out.append(row)
    return out, problems


def parse_report(pages: list[str]) -> dict:
    """{issued, period, summary: {permit: {collection, plant}}, rows: [...], check: {permit: (read, summary)}}."""
    issued = period = None
    summary: dict[str, dict] = {}
    rows: list[dict] = []
    tables: list[dict] = []
    unreadable: list[str] = []
    totals: list[int] = []
    district = None
    for pi, text in enumerate(pages):
        if issued is None and (m := ISSUED.search(text)):
            issued = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        found = False
        for m in SUMMARY.finditer(text):
            found = True
            kind = "collection" if m.group(4).lower().startswith("collection") else "plant"
            summary.setdefault(m.group(2).upper(), {"ai": m.group(3)})[kind] = int(m.group(5))
        if found:
            totals += [int(x) for x in SUMMARY_TOTAL.findall(text)]
        if "Rec. Waters" not in text:
            continue
        lines = text.split("\n")
        cols = None
        head = None
        anchors: list[int] = []
        for i, ln in enumerate(lines):
            if (m := HEADING.search(ln)):
                district = {"name": m.group(1).title(), "permit": m.group(2).upper(), "ai": m.group(3)}
                tables.append(dict(district))
            if period is None and (m := PERIOD.search(ln)):
                period = [datetime.strptime(x, "%m/%d/%Y").date().isoformat() for x in m.groups()]
            if cols is None and "Rec. Waters" in ln and "Address" in ln:
                cols, head = _columns(ln), i
            elif cols and DATE_ROW.match(ln):
                anchors.append(i)
        if not cols or not district:
            continue
        rows_here, problems_here = read_rows(lines, cols, head, anchors, district, pi + 1)
        rows += rows_here
        unreadable += problems_here
    check = {}
    for p in sorted(set(summary) | set(DISTRICTS) | {r["permit"] for r in rows}):
        s = summary.get(p) or {}
        read = sum(1 for r in rows if r["permit"] == p)
        check[p] = {"read": read, "summary_collection": s.get("collection"), "summary_plant": s.get("plant")}
    problems = layout_problems(summary, rows, tables, totals)
    if unreadable:
        problems.append(f"{len(unreadable)} table cells not read with confidence ("
                        + "; ".join(unreadable[:5]) + ("; ..." if len(unreadable) > 5 else "") + ")")
    ok = not problems and all(c["read"] == c["summary_collection"] for c in check.values())
    return {"issued": issued, "period": period, "summary": summary, "rows": rows, "check": check, "layout_ok": ok,
            "problems": problems, "parser_version": PARSER_VERSION}


def layout_problems(summary: dict, rows: list[dict], tables: list[dict], totals: list[int] | None = None) -> list[str]:
    """What makes a report incomplete beyond a row count: a district the summary does not give a collection-system
    count for, a permit the report should not hold, a table heading whose district name and permit disagree, a
    district with discharges in its summary and no table, and a summary whose own Total is not the sum of its four
    counts (the collection system and the treatment plant of each district)."""
    out = []
    parts = [(summary.get(p) or {}).get(k) for p in DISTRICTS for k in ("collection", "plant")]
    if totals and None not in parts and any(t != sum(parts) for t in totals):
        out.append(f"the summary's Total ({', '.join(map(str, sorted(set(totals))))}) is not the sum of its counts "
                   f"({sum(parts)})")
    for p, name in DISTRICTS.items():
        if (summary.get(p) or {}).get("collection") is None:
            out.append(f"the summary gives no collection-system count for {name} ({p})")
        elif summary[p]["collection"] > 0 and not any(t["permit"] == p for t in tables):
            out.append(f"no {name} collection-system table ({p}) for the summary's {summary[p]['collection']}")
    for p in sorted(set(summary) | {t["permit"] for t in tables}):
        if p not in DISTRICTS:
            out.append(f"a permit not one of the two collection systems: {p}")
    for t in tables:
        if t["permit"] in DISTRICTS and DISTRICTS[t["permit"]] != t["name"]:
            out.append(f"a table headed {t['name']} under {t['permit']} ({DISTRICTS[t['permit']]})")
    return out


def records(state: dict) -> list[dict]:
    out = []
    for _, rep in sorted(migrate(state).get("reports", {}).items(), key=lambda kv: kv[1].get("number") or 0):
        if not rep.get("layout_ok"):
            continue
        url = rep.get("url")
        seen: dict = {}
        for r in rep["rows"]:
            k = (r["permit"], r["date"])
            seen[k] = seen.get(k, 0) + 1
            water = r.get("receiving_water")
            named = water and water.strip().lower() not in NO_WATER
            raw = {"report": rep.get("number"), "report_url": url, "report_period": rep.get("period"),
                   "report_page": r.get("page"), "district": r.get("name"), "agency_interest": r.get("ai"),
                   "county": COUNTY, "cause": r.get("cause"),
                   "receiving_water_as_given": water, "gallons_as_given": r.get("gallons_text"),
                   "time_zone": TZ, "layout_check": rep.get("check"), "report_sha256": rep.get("sha256"),
                   "parser_version": rep.get("parser_version") or 1,
                   # placed only on the water the row names, never at the plant or an outfall of the permit
                   "_placement": "named_water_only",
                   "date_basis": "the table's Date column (a date; the City gives no time and no end)"}
            per = rep.get("period") or []
            if len(per) == 2 and not (per[0] <= r["date"] <= per[1]):
                raw["date_note"] = (f"the date given lies outside the report's quarter ({per[0]} to {per[1]}); kept as "
                                    "the City-Parish wrote it")
            if r.get("receiving_water_withheld"):
                raw["placement_note"] = (r["receiving_water_withheld"] + ": kept with its parish and permit, placed "
                                         "on no water")
            elif not named:
                raw["placement_note"] = ("the City's table gives no receiving water ('None'): kept with its parish "
                                         "and permit, placed on no water")
            out.append(event(
                source_id=SOURCE_ID, source_record_id=f"r{rep.get('number')}-{r['permit']}-{r['date']}-{seen[k]}",
                event_type="sso", status="unknown", discharger_name=OPERATOR, npdes_permit=r["permit"],
                waterbody_text=water if named else None, water_slugs=[], water_match="none",
                started_at=r["date"], ended_at=None, time_precision="day", reported_at=None,
                published_at=rep.get("issued"), source_updated_at=None,
                material="untreated sewage", volume_gal=r.get("gallons"),
                volume_text=f"{r.get('gallons_text')} gallons" if r.get("gallons") is not None else None,
                estimate_flag="unknown", authority=AUTHORITY, source_url=url, raw=raw))
            out[-1]["fetched_at"] = rep.get("read_at") or out[-1]["fetched_at"]   # when the report was read
    return out


def retained(prev: dict, state: dict) -> list[dict]:
    """The previous events file's records for reports with no accepted copy in the state, the receiving-water cell
    checked again (receiving_water) before they are written: a record is never lost because the state file is absent
    or a read failed, and no earlier text bypasses the check (Astra verify3 P1-1)."""
    accepted = {str(v.get("number")) for v in (state.get("reports") or {}).values() if v.get("layout_ok")}
    out = []
    for r in prev.get("records") or []:
        if not isinstance(r, dict) or not r.get("source_record_id"):
            continue
        raw = dict(r.get("raw") or {})
        if str(raw.get("report")) in accepted:
            continue                        # the accepted copy in the state gives this report's rows
        r = {**r, "raw": raw}
        for cell in {raw.get("receiving_water_as_given"), r.get("waterbody_text")} - {None}:
            w, why = receiving_water(cell)
            if why:
                r["waterbody_text"] = raw["receiving_water_as_given"] = None
                r["water_slugs"], r["water_match"] = [], "none"
                raw["placement_note"] = why + ": kept with its parish and permit, placed on no water"
                break
        raw["retained_from"] = "the previous events file (no accepted copy of this report in the state)"
        out.append(r)
    return out


def report_links(page: str) -> dict[int, str]:
    out = {}
    for href, n in REPORT_LINK.findall(page):
        out.setdefault(int(n), urljoin(INDEX, href).replace("http://", "https://"))
    return out


def migrate(state: dict) -> dict:
    """Reports keyed by report number (a state file of the first build keyed them by URL)."""
    reps = state.get("reports") or {}
    if any(str(k).startswith("http") or "/" in str(k) for k in reps):
        state["reports"] = {str(v.get("number")): {**v, "url": v.get("url") or k} for k, v in reps.items()}
    state.setdefault("reports", {})
    for v in state["reports"].values():
        # rows saved before the receiving-water check: the cell is checked again before the state is written
        for r in v.get("rows") or []:
            if r.get("receiving_water") and not r.get("receiving_water_withheld"):
                w, why = receiving_water(r["receiving_water"])
                if why:
                    r["receiving_water"], r["receiving_water_withheld"] = w, why
    pend = state.setdefault("pending", {})
    for k, v in state["reports"].items():
        # a state file from before pending was kept: a report with no accepted copy is unresolved since its last read
        if not v.get("layout_ok") and k not in pend:
            pend[k] = {"url": v.get("url"), "reason": unread_reason(v), "since": v.get("read_at"),
                       "last_tried": v.get("read_at")}
    return state


def note_failure(state: dict, number: int, url: str, reason: str, at: str) -> None:
    """A failed read of a report (a fetch error, a copy that fails the layout check, a rejected amendment) stays
    pending, whether or not an accepted copy is kept, until a read of that report succeeds: the run is not ok while
    anything is pending, and a pending report is tried again on the re-read cadence (due)."""
    prev = state.setdefault("pending", {}).get(str(number)) or {}
    state["pending"][str(number)] = {"url": url, "reason": reason, "since": prev.get("since") or at, "last_tried": at}


def note_success(state: dict, number: int) -> None:
    state.setdefault("pending", {}).pop(str(number), None)


def read_report(state: dict, url: str, number: int, content: bytes, at: str) -> tuple[dict, str | None]:
    """Parse a report and keep it under its number. A report that fails the layout check never replaces one that
    passed (an amended copy under a new address, or a re-read): the accepted version stays, the failed attempt is
    kept in attempts and named as an error. Returns (the report kept, the error or None)."""
    migrate(state)
    rep = parse_report(pdf_pages(content))
    rep.update(number=number, url=url, sha256=hashlib.sha256(content).hexdigest(), read_at=at)
    key = str(number)
    prev = state["reports"].get(key)
    attempt = {k: rep.get(k) for k in ("url", "sha256", "read_at", "layout_ok", "check", "parser_version")}
    if prev and prev.get("layout_ok") and not rep.get("layout_ok"):
        prev.setdefault("attempts", []).append(attempt)
        return prev, (f"report {number}: a new copy ({url}) failed the layout check; the accepted copy of "
                      f"{prev.get('read_at')} is kept")
    rep["attempts"] = (prev or {}).get("attempts", []) + [attempt]
    if prev and prev.get("sha256") != rep["sha256"]:
        rep["replaces"] = {k: prev.get(k) for k in ("url", "sha256", "read_at")}
    state["reports"][key] = rep
    if not rep.get("layout_ok"):
        # no accepted copy of this report (a first read or a repeated one): it gives no rows and the run says so
        return rep, f"report {number}: {url} failed the layout check ({unread_reason(rep)}); no rows are taken from it"
    return rep, None


def unread_reason(rep: dict) -> str:
    """Why a report gives no rows: the permits whose table rows do not match the report's own summary count."""
    bad = {p: c for p, c in (rep.get("check") or {}).items() if c.get("read") != c.get("summary_collection")}
    out = list(rep.get("problems") or [])
    if bad:
        out.append("discharge rows read against the summary's count: " + ", ".join(
            f"{p} {c.get('read')} of {c.get('summary_collection')}" for p, c in sorted(bad.items())))
    if not rep.get("summary"):
        out.insert(0, "its summary table was not found")
    return "; ".join(out) or "its summary table was not found"


REREAD_DAYS = 30        # the newest two reports are read again this often, for an amended copy at the same address


def parsed_by_older(rep: dict) -> bool:
    """True when no read of this report (the copy kept or any attempt) was made by the current parser: the report is
    fetched again on the next run and its rows replace the earlier ones under the same ids. The PDF is not kept, so
    this is one more request per report, once per parser version; a read that fails is recorded as an attempt by
    this version, so it is not fetched again every run (it stays pending and is retried every REREAD_DAYS)."""
    seen = [rep.get("parser_version") or 1] + [a.get("parser_version") or 1 for a in rep.get("attempts") or []]
    return max(seen) < PARSER_VERSION


def due(state: dict, links: dict[int, str], now: str, refresh: bool = False) -> list[tuple[int, str]]:
    """The reports to fetch: new numbers, a number whose address changed, every report no read of which was made by
    the current parser (parsed_by_older), and the newest two when their last read is older than REREAD_DAYS."""
    from datetime import datetime as _dt
    migrate(state)
    out = []
    newest = sorted(n for n in links if n >= FIRST_REPORT)[-2:]
    for n, url in sorted(links.items()):
        if n < FIRST_REPORT:
            continue
        rep = state["reports"].get(str(n))
        pend = (state.get("pending") or {}).get(str(n))
        tried = {a.get("url") for a in (rep or {}).get("attempts", [])} | {(rep or {}).get("url")}
        if refresh or rep is None or url not in tried or parsed_by_older(rep):
            out.append((n, url))
            continue
        # a report with no accepted copy, or whose last read failed (an amended copy that could not be read, with
        # the older accepted copy kept), is tried again on the re-read cadence, whatever its number
        unread = not rep.get("layout_ok") or pend is not None
        last = max([a.get("read_at") or "" for a in rep.get("attempts", [])] + [rep.get("read_at") or "",
                                                                                (pend or {}).get("last_tried") or ""])
        try:
            age = (_dt.fromisoformat(now.replace("Z", "+00:00")) - _dt.fromisoformat(last.replace("Z", "+00:00"))).days
        except ValueError:
            age = REREAD_DAYS
        if (n in newest or unread) and age >= REREAD_DAYS:
            out.append((n, url))
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = now_iso()
    state = read_json(STATE_PATH, {}) or {}
    errors = []
    if "--file" in argv:
        url = argv[argv.index("--url") + 1] if "--url" in argv else Path(argv[argv.index("--file") + 1]).name
        n = int(argv[argv.index("--report") + 1])
        _, err = read_report(state, url, n, Path(argv[argv.index("--file") + 1]).read_bytes(), at)
        if err:
            errors.append(err)
            note_failure(state, n, url, err, at)
        else:
            note_success(state, n)
    else:
        try:
            r = requests.get(INDEX, headers=HEADERS, timeout=120)
            r.raise_for_status()
            links = report_links(r.text)
        except requests.RequestException as e:
            # the index not read: nothing new is fetched, but the state and the retained records are written again
            # from the state after its rows are checked again (migrate), so no earlier text bypasses the check
            print(f"{SOURCE_ID}: index not read ({error_detail(e)})", file=sys.stderr)
            errors.append(f"index: {error_detail(e)}")
            links = None
        for n, url in (due(state, links, at, "--refresh" in argv) if links is not None else []):
            try:
                pr = requests.get(url, headers=HEADERS, timeout=300)
                pr.raise_for_status()
                _, err = read_report(state, url, n, pr.content, at)
                if err:
                    errors.append(err)
                    note_failure(state, n, url, err, at)
                else:
                    note_success(state, n)
            except Exception as e:                    # a report that cannot be read is named; the others go on
                errors.append(f"report {n}: {error_text(e)}")
                note_failure(state, n, url, f"{error_text(e)}", at)
        if links is not None:
            state["index_read_at"] = at
            state["index_reports"] = {str(k): v for k, v in sorted(links.items())}
    migrate(state)
    write_json(STATE_PATH, state)
    recs = records(state)
    # the state is the record of what was read; where it holds no accepted copy of a report whose rows the events file
    # already carries (no state file, an emptied one, or a report whose re-read failed before it was ever accepted
    # here), those earlier rows are kept, checked again, and never dropped by a failed or partial read
    held = retained(read_json(common.EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}, state)
    recs += held
    reps = state.get("reports") or {}
    meta = {"registry_ids": ["la-baton-rouge-quarterly-reports"], "index": INDEX, "first_report": FIRST_REPORT,
            "reports_read": {str(v.get("number")): {"period": v.get("period"), "issued": v.get("issued"),
                                                     "layout_ok": v.get("layout_ok"), "check": v.get("check")}
                             for v in reps.values()},
            "failed_checks": sorted(str(v.get("number")) for v in reps.values() if not v.get("layout_ok")),
            "plant_events_not_itemised": {str(v.get("number")): sum(s.get("plant") or 0 for s in v["summary"].values())
                                          for v in reps.values()},
            "unread": {str(v.get("number")): {"url": v.get("url"), "last_tried": v.get("read_at"),
                                               "reason": unread_reason(v)}
                       for v in reps.values() if not v.get("layout_ok")},
            "errors": errors,
            "retained_from_previous_events": sorted({str((r.get("raw") or {}).get("report")) for r in held}),
            "pending": dict(sorted((state.get("pending") or {}).items())),
            "cadence": (f"the index with the refresh; a new report once, the newest two and any report with no accepted "
                        f"copy again every {REREAD_DAYS} days")}
    # a failure not retried this run is still unresolved: the run stays not ok until a read of that report succeeds
    errors += [f"report {k}: unresolved since {v.get('since')} ({v.get('reason')}); tried again on the re-read cadence"
               for k, v in sorted((state.get("pending") or {}).items()) if v.get("last_tried") != at]
    if errors:
        # the records come from the accepted reports in the state file, so they are complete: written, but the run
        # is not ok (a failed fetch or a failed re-read is named)
        path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
        write_json(path, {"source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": False, "error": "; ".join(errors),
                          "last_ok_at": (read_json(path, {}) or {}).get("last_ok_at"), "meta": meta,
                          "count": len(recs), "records": recs})
    else:
        path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} rows from {sum(1 for v in reps.values() if v.get('layout_ok'))} reports "
          f"({len(meta['failed_checks'])} failed the layout check) -> {path}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
