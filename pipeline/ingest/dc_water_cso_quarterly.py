"""DC Water's combined sewer system quarterly reports: the dated overflows of Table 2-7 -> data/build/events/
dc-water-cso-quarterly.json.

Source
  DC Water's publications list, "CSO Division Quarterly Operation Reports"
  (https://www.dcwater.com/resources/publications?term_node_tid_depth=50, registry dc-dcwater-cso-quarterly-reports),
  which the 2003 three-party consent decree (section V.16.b) and permit DC0021199 (Part III) require: one PDF per
  quarter, each holding the three monthly "Monthly Operations Report for Combined Sewer System" sections and the
  quarter's "Combined Sewer System Model Results" table. The list's first page reaches back to the third quarter of
  2020, the later pages to the first quarter of 2005; each row gives the document date (the publication date used
  here) and a title "<year> <n>th QUARTER COMBINED SEWER OVERFLOW FACILITIES QUARTERLY REPORT".

What is read (Table 2-7, "Inflatable Dams & SCADA Sites - Wet Weather Operations", one per month)
  For each inflatable dam structure (14 (E & W), 15, 15A, 16 (E & W), 34, 35, 52) the "Overflow Dates" and the
  "Estimated Duration of Overflow" ("9/11/26 47mins"), and the same for the three structures on the outfall sewers
  (Outfall Structure 1, 1A, 2). One record per date at a structure: event_type cso, started_at the date
  (time_precision day: the table gives no clock time, so none is made up), ended_at null, status ended (DC Water gives
  a duration, so the overflow ended; its end time is not given), raw.duration_minutes and raw.duration_as_given as
  DC Water wrote them ("estimated", DC Water's word for the duration). No volume: Table 2-7 gives none.
  data/rules.json unresolved.day_start_caution gives the site's caution for 72 hours from the start of that day.
  published_at is the report's document date on the list (weeks after the quarter), never the overflow's date;
  fetched_at is when the report was read.
  A date the table's own numbered notes deny ("On 9/03/20, Structure 14 (E & W) ... This was not an overflow to the
  river"), naming that structure and that date, is set apart: no record, listed in meta.set_apart with the note's
  number (the notes' text is not kept). A denying note that names no structure or no date makes that month unread.

Structures and outfalls (STRUCTURE_OUTFALL)
  A structure is tied to a registry outfall of DC0021199 only through DC Water's own Table 2-1, "Regulator
  Structures", column "Associated NPDES Outfall", which every monthly section prints: 14 -> 011(a), 15 and 15a -> 010,
  16 -> 012, 34 -> 020, 35 -> 021, 52 -> 034 (second quarter of 2026, pages 3 to 6). When the report's own Table 2-1
  is readable it is used, and a structure it ties to another outfall, or does not list, is tied as it says, or not
  at all; when it is not readable (pages without a text layer) the reference transcription above is used and
  raw.tie_basis says so. The three outfall-sewer structures are not in Table 2-1 and are tied to no outfall. The
  record takes the registry outfall's point and water (data/outfalls-mid-atlantic.json, water_match
  outfall_registry): never coordinates from anywhere else. waterbody_text is the river DC Water's model table files
  the outfall under (Anacostia, Potomac, Rock Creek; RIVER_OF_OUTFALL).

Quarterly totals and EPA's records (never one overflow twice)
  The report's last table, the quarter's modeled and metered totals per outfall, is not turned into records: a
  dated overflow at a structure is one of the occurrences its outfall's total counts, so a total next to the dated
  records would count it twice. The site showed no such totals before this feed (no feed read them), so nothing
  shown is dropped. An EPA Sewer Overflow and Bypass Event row of DC0021199 (data/build/events/echo-sewer-overflow.json)
  at the same outfall, starting on the same local day, is the structured record of the same overflow: this
  record gets duplicate_of that row and sets no colour (the rule dc_water_news uses).

Dry weather overflows
  Section 3 states each month whether a dry weather overflow was reported. A month that states one is listed in
  meta.dry_weather_statements (month, outfalls named); the narrative is not itemised (DC Water reports those to EPA,
  whose rows the ECHO feed reads).

Reading and failure (pypdf, plain text; the PDF is never saved)
  A month is read when its Table 2-7 is found on a page with a text layer, its header and its seven dam structures
  and three outfall-sewer structures are all present, every structure row's dates and durations pair up (or the
  row gives dates and no duration at all), and every denying note names its structure and date. Otherwise the month
  is unread (meta.unread with the reason: no text layer, a missing structure, a changed header, a file encrypted
  with a password; one that opens with the empty user password, as 2023Q2 does, is read);
  the months that were read give their records, the run is ok=False while anything is unread (partial: the records
  are written, last_ok_at stays), and a month read earlier is never replaced by a failed read of a later copy.
  A changed header or an unknown structure fails loudly as a changed table.

Keys and revisions
  The state (data/build/dc-water-cso-quarterly-state.json) keeps each quarter ("2026Q3") with its address, SHA-256,
  parser version, every read (attempts) and per month the rows read. source_record_id is
  "s<structure>-<date>-<n>" (n: the date's order among that structure's dates in that month's table), so a revised
  report of the same quarter updates its records and never duplicates them; a row a revised copy no longer lists is
  kept with raw.not_in_revision. A quarter is fetched when new, when its address changed, when no read was made by the
  current parser, and the newest two quarters and any quarter with an unread month every REREAD_DAYS. Where the state
  holds nothing for a quarter whose records the previous events file carries, those records are kept.

Cadence
  The list is read at most every INDEX_EVERY_H hours (a report is issued once a quarter, about four weeks after it
  ends); the records are written from the state on every run. The regular run reads the list's first page (the
  quarters from FIRST_QUARTER on that it shows); --backfill reads every page and every quarter from FIRST_QUARTER
  (2020Q1; older reports use earlier layouts and are listed in meta.not_read, not failed); --refresh reads every due
  quarter again.

Exit code: the hourly run exits 1 while anything is unread. --backfill exits 0 when the list was read and at least
  one month is read (the unread months are named in meta.unread, the error and the output line, and health stays
  false), and 1 when the list was not read or no month was read (backfill_exit).

Run from pipeline/: python -m ingest.dc_water_cso_quarterly [--backfill] [--refresh] [--file report.pdf --quarter 2026Q3]
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests

import common
from common import BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, write_events, write_json

SOURCE_ID = "dc-water-cso-quarterly"
REGISTRY_ID = "dc-dcwater-cso-quarterly-reports"
INDEX = "https://www.dcwater.com/resources/publications?term_node_tid_depth=50"
STATE_PATH = BUILD_DIR / "dc-water-cso-quarterly-state.json"
ECHO_FILE = EVENTS_DIR / "echo-sewer-overflow.json"
PERMIT = "DC0021199"
DISCHARGER_ID = "dc-dc0021199"
DISCHARGER_NAME = "District of Columbia Water and Sewer Authority (DC Water)"
AUTHORITY = ("DC Water, Combined Sewer Overflow Facilities Quarterly Report (Table 2-7, Inflatable Dams & SCADA "
             "Sites - Wet Weather Operations)")
MATERIAL = "combined sewage and stormwater"
FIRST_QUARTER = (2020, 1)
PARSER_VERSION = 1
REREAD_DAYS = 30
INDEX_EVERY_H = 24
MAX_INDEX_PAGES = 40
SECTION_PAGES = 4         # Table 2-7's page, its notes, section 3 and section 4's heading
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]

# Table 2-1 "Regulator Structures", "Associated NPDES Outfall", as DC Water prints it in the report for the second
# quarter of 2026 (pages 3 to 6 of each monthly section); used where a report's own Table 2-1 has no text layer
STRUCTURE_OUTFALL = {"14": "011A", "15": "010", "15A": "010", "16": "012", "34": "020", "35": "021", "52": "034"}
STRUCTURE_OUTFALL_BASIS = ("DC Water's Table 2-1 'Regulator Structures', column 'Associated NPDES Outfall' (CSO "
                           "quarterly report, second quarter of 2026)")
# the river DC Water's "Combined Sewer System Model Results" table files each outfall under
RIVER_OF_OUTFALL = {"010": "Anacostia River", "011A": "Anacostia River", "012": "Anacostia River",
                    "020": "Potomac River", "021": "Potomac River", "034": "Rock Creek"}

# the rows of Table 2-7, as labelled in the table (the two dams of 14 and 16 share one row each)
DAM_LABELS = [("14", r"14\s*\(\s*E\s*&\s*W\s*\)"), ("15A", r"15\s*A"), ("15", r"15"),
              ("16", r"16\s*\(\s*E\s*&\s*W\s*\)"), ("34", r"34"), ("35", r"35"), ("52", r"52")]
OUTFALL_SEWER_LABELS = [("OS1A", r"Outfall\s+Structure\s+1A"), ("OS1", r"Outfall\s+Structure\s+1"),
                        ("OS2", r"Outfall\s+Structure\s+2")]
STRUCTURE_NAME = {"14": "inflatable dam structure 14 (east and west)", "15": "inflatable dam structure 15",
                  "15A": "inflatable dam structure 15A", "16": "inflatable dam structure 16 (east and west)",
                  "34": "inflatable dam structure 34", "35": "inflatable dam structure 35",
                  "52": "inflatable dam structure 52", "OS1": "outfall sewer structure 1",
                  "OS1A": "outfall sewer structure 1A", "OS2": "outfall sewer structure 2"}
HEADER = re.compile(r"Inflatable\s+Dam\s+Structure\s+No\.?\s+Overflow\s+Dates\s+Estimated\s+Duration\s+of\s+Overflow",
                    re.I)
OS_HEADER = re.compile(r"Structures\s+on\s+Outfall\s+Sewers\s+Overflow\s+Dates\s+Estimated\s+Duration", re.I)
TABLE_END = re.compile(r"Outfall\s+Sewer\s+Control\s+Gates", re.I)
SECTION_END = re.compile(r"^\s*4\.\s*SOLIDS\s+AND\s+FLOATABLES|^\s*4\.1\s+Catch\s+Basin", re.I | re.M)
DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2,5})(?![\d/])")
DURATION = re.compile(r"(?<![\w/])(?:(\d+)\s*(?:hrs?|hours?)\.?,?\s*(?:(\d+)\s*(?:mins?|minutes?)\.?)?|(\d+)\s*(?:mins?|minutes?)\.?)"
                      r"(?:,?\s*(\d+)\s*(?:secs?|seconds?|s)\b\.?)?", re.I)
FOOTNOTES = r"(?:\s*\d{1,2}(?:\s*,\s*\d{1,2})*)?"
# a row that starts like a structure's (a number or 'Outfall Structure <x>', then a date or 'None') but is none of the
# known labels: the table changed, and its dates must never fall to the row above
UNKNOWN_ROW = re.compile(r"^\s*(?:Outfall\s+Structure\s+\w+|\d{1,3}\s*[A-Za-z]?(?:\s*\([^)]*\))?(?:\d{1,2}(?:\s*,\s*\d{1,2})*)?)"
                         r"\s+(?:\d{1,2}/\d{1,2}/\d{2}|None\b)", re.I)
GLYPHS = re.compile(r"(?:^|(?<=\s))/i?\d+(?=\s|/|$)", re.M)
REPORT_FOR = re.compile(r"Report\s+for\s+(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})", re.I)
NOTE = re.compile(r"(?m)^\s*(\d{1,2})\.\s+(?=[A-Z][a-z]|A\b)")     # a numbered note; never "3. DRY WEATHER"
DENIAL = re.compile(r"\b(?:was|were|is)\s+not\s+(?:an?\s+)?overflows?\s+(?:to|into)\s+the\s+(?:river|receiving\s+water)|"
                    r"\bnot\s+discharged\s+to\s+the\s+river|\bno\s+overflow\s+(?:to|into|occurred\s+to)\s+the\s+river", re.I)
NOTE_STRUCTURES = re.compile(r"Structures?\s+((?:(?:\d{1,2}\s*A?)(?:\s*\(\s*E\s*&\s*W\s*\))?(?:\s*(?:,|and|&)\s*)?)+)", re.I)
DWO = re.compile(r"There\s+(?:was|were)\s+(one|two|three|four|five|\d+|no)\s*(?:\(\d+\)\s*)?dry\s*weather\s+combined\s+"
                 r"sewer\s+overflows?\s+reported\s+during\s+(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})([^.]*)", re.I)
TITLE = re.compile(r"(\d{4})\s+(\d)\s*(?:st|nd|rd|th)\s+quarter\s+combined\s+sewer\s+overflow\s+facilities\s+quarterly",
                   re.I)


class UnreadableReport(Exception):
    """The file cannot be read at all (encrypted with a cipher pypdf cannot open here, or not a PDF)."""


# ---------------------------------------------------------------- the list of reports

def quarter_key(year: int, q: int) -> str:
    return f"{year}Q{q}"


def parse_index(html: str, base: str = INDEX) -> tuple[list[dict], list[dict]]:
    """([{quarter, year, q, published, url}], [rows whose title gives no quarter]) from one list page."""
    out, odd = [], []
    for row in re.findall(r"<tr.*?</tr>", html, re.S | re.I):
        cells = [" ".join(re.sub(r"<[^>]+>", " ", c).split()) for c in re.findall(r"<td.*?</td>", row, re.S | re.I)]
        pdfs = [h for h in re.findall(r'href="([^"]+)"', row) if h.lower().split("?")[0].endswith(".pdf")]
        if not cells or not pdfs or "quarterly" not in " ".join(cells).lower():
            continue
        text = " ".join(cells)
        try:
            published = datetime.strptime(cells[0], "%B %d, %Y").date().isoformat()
        except ValueError:
            published = None
        url = urljoin(base, pdfs[0].replace("&amp;", "&"))
        m = TITLE.search(text)
        if not m or not 1 <= int(m.group(2)) <= 4:
            odd.append({"published": published, "url": url, "reason": "the title names no year and quarter"})
            continue
        y, q = int(m.group(1)), int(m.group(2))
        out.append({"quarter": quarter_key(y, q), "year": y, "q": q, "published": published, "url": url})
    return out, odd


def index_pages(html: str) -> int:
    """The number of list pages the first page links to (page=0 .. page=N)."""
    ns = [int(x) for x in re.findall(r"[?&](?:amp;)?page=(\d+)", html)]
    return max(ns, default=0) + 1


# ---------------------------------------------------------------- reading a report

def pdf_pages(content: bytes) -> list[str]:
    import pypdf
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        # an encrypted report that opens with the empty user password (2023Q2: AES-128, which pypdf decrypts with the
        # cryptography package, pipeline/requirements.txt) is read; one that needs a real password is not
        if reader.is_encrypted and reader.decrypt("") == pypdf.PasswordType.NOT_DECRYPTED:
            raise UnreadableReport("the file is encrypted with a password: not read")
        return [p.extract_text() or "" for p in reader.pages]
    except pypdf.errors.DependencyError as e:
        raise UnreadableReport(f"the file is encrypted with a cipher this reader cannot open ({e})") from e
    except pypdf.errors.PdfReadError as e:
        raise UnreadableReport(f"not a readable PDF ({e})") from e


def no_text_layer(page: str) -> bool:
    """A page whose text is glyph codes ('/0 /1 /i255': its fonts carry no Unicode map) or that gives no text at all
    (an image): it cannot be read."""
    return len(GLYPHS.findall(page)) > 30 or len(page.strip()) < 20


def quarter_months(year: int, q: int) -> list[str]:
    return [f"{year}-{m:02d}" for m in range(3 * q - 2, 3 * q + 1)]


def _page_month(page: str) -> str | None:
    m = REPORT_FOR.search(page)
    if not m:
        return None
    return f"{int(m.group(2))}-{MONTH_NAMES.index(m.group(1).title()) + 1:02d}"


def month_sections(pages: list[str]) -> dict[str, tuple[int, str]]:
    """{YYYY-MM: (first page number, the text of Table 2-7 to the end of section 3)}: from the page that holds
    Table 2-7's header to the heading of section 4 (at most SECTION_PAGES pages of the same month). A section whose
    end is not found on text (a page on the way has no text layer, or no page holds the heading) is returned with the text None: its notes
    may be on the page that cannot be read, so the month is unread (Astra review 2026-11-16 P1)."""
    out = {}
    for i, p in enumerate(pages):
        if no_text_layer(p) or not HEADER.search(p):
            continue
        month = _page_month(p)
        if month is None or month in out:
            continue
        # the section runs over the following pages of the same month (notes, section 3) to section 4's heading
        parts, text = [], None
        for j in range(i, min(i + SECTION_PAGES, len(pages))):
            pj = pages[j]
            if j > i and (no_text_layer(pj) or HEADER.search(pj) or _page_month(pj) not in (None, month)):
                break
            cut = SECTION_END.search(pj)
            if cut:
                text = "\n".join(parts + [pj[:cut.start()]])
                break
            parts.append(pj)
        out[month] = (i + 1, text)
    return out


def _iso(m: re.Match) -> str | None:
    """The ISO day of an m/d/yy or m/d/yyyy date, or None (a year of three or five digits, '8/3/20024', is not read
    as any year: the month is then unread, never guessed)."""
    y = m.group(3)
    if len(y) not in (2, 4):
        return None
    try:
        return date(2000 + int(y) if len(y) == 2 else int(y), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _minutes(m: re.Match) -> float:
    h = int(m.group(1)) if m.group(1) else 0
    mins = int(m.group(2) or m.group(3) or 0)
    secs = int(m.group(4)) if m.group(4) else 0
    return round(h * 60 + mins + secs / 60, 2)


def _label_line(line: str, labels) -> tuple[str, list[int], str] | None:
    """(structure key, its footnote marks, the rest of the line) when the line starts a row of the table: its label,
    its footnote marks ('357' is structure 35 with note 7; '14 (E & W)2, 5,6'), then a date or 'None' (a duration line
    such as '15 mins' never starts a row)."""
    for key, pat in labels:
        m = re.match(rf"\s*{pat}(?![\dA-Za-z(])({FOOTNOTES})\s+(?=\d{{1,2}}/\d{{1,2}}/\d{{2}}|None\b)", line) or \
            re.match(rf"\s*{pat}(?=\d{{1,2}}(?:\s*,\s*\d{{1,2}})*\s+(?:\d{{1,2}}/\d{{1,2}}/\d{{2}}|None\b))"
                     rf"({FOOTNOTES})\s+", line)
        if m:
            return key, [int(x) for x in re.findall(r"\d+", m.group(1) or "")], line[m.end():]
    return None


def _rows(block: str, labels, month: str, problems: list[str]) -> dict[str, dict]:
    """{structure: {dates, durations, none}} of one block of Table 2-7."""
    rows: dict[str, dict] = {}
    cur = None
    for line in block.split("\n"):
        if not line.strip():
            continue
        hit = _label_line(line, labels)
        if not hit and UNKNOWN_ROW.match(line):
            problems.append(f"{month}: an unknown structure row in Table 2-7 (a changed table)")
            cur = None
            continue
        if hit:
            cur, marks, rest = hit
            if cur in rows:
                problems.append(f"{month}: structure {cur} listed twice in Table 2-7")
            rows[cur] = {"text": [rest], "marks": marks}
        elif cur is not None:
            rows[cur]["text"].append(line)
    for key, r in rows.items():
        text = " ".join(r.pop("text"))
        text = re.sub(r"This structure has been bulk\s*headed\.?\s*Overflows are no longer possible\.?", " ", text,
                      flags=re.I)
        dates = [(m.group(0), _iso(m)) for m in DATE.finditer(text)]
        rest = DATE.sub(" ", text)
        durs = [(" ".join(m.group(0).split()), _minutes(m)) for m in DURATION.finditer(rest)]
        r.update(dates=dates, durations=durs, none=bool(re.search(r"\bNone\b", text)))
        bad = [g for g, d in dates if d is None]
        if bad:
            problems.append(f"{month}: structure {key}: a date that is not a calendar day ({', '.join(bad)})")
        if r["none"] and dates:
            problems.append(f"{month}: structure {key}: 'None' and dates in one row")
        if dates and durs and len(durs) != len(dates):
            problems.append(f"{month}: structure {key}: {len(dates)} dates and {len(durs)} durations")
        if not dates and not r["none"]:
            problems.append(f"{month}: structure {key}: neither dates nor 'None'")
    return rows


def denying_notes(text: str, month: str, problems: list[str]) -> list[dict]:
    """[{note, structures, dates}] of the numbered notes that say a deflation or overflow date was not an overflow to
    the river; a denying note that names no structure or no date is a problem (its row cannot be told)."""
    out = []
    starts = list(NOTE.finditer(text))
    for i, m in enumerate(starts):
        body = text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        body = re.split(r"\n\s*3\.\s+DRY\s+WEATHER|Inflatable\s+Dam\s+Structure\s+No", body, flags=re.I)[0]
        body = " ".join(body.split())
        for sentence_group in [body]:
            if not DENIAL.search(sentence_group):
                continue
            # the structures and dates of the sentences before the denial (the note's own event)
            head = sentence_group[:DENIAL.search(sentence_group).start()]
            dates = sorted({d for d in (_iso(x) for x in DATE.finditer(head)) if d})
            structs = set()
            for sm in NOTE_STRUCTURES.finditer(head):
                for s in re.findall(r"\d{1,2}\s*A?", sm.group(1)):
                    structs.add(re.sub(r"\s+", "", s).upper())
            if not structs:
                problems.append(f"{month}: note {m.group(1)} says not an overflow to the river but names no structure")
                continue
            out.append({"note": int(m.group(1)), "structures": sorted(structs), "dates": dates,
                        "denial": " ".join(DENIAL.search(sentence_group).group(0).split())})
    return out


def parse_month(text: str, month: str) -> dict:
    """{status: read|unread, reason, rows: [...], set_apart: [...], dwo}."""
    problems: list[str] = []
    h = HEADER.search(text)
    oh = OS_HEADER.search(text)
    if not h or not oh or oh.start() < h.start():
        return {"status": "unread", "reason": f"{month}: Table 2-7's header changed or is missing (a changed table)"}
    end = TABLE_END.search(text, oh.end())
    dams = _rows(text[h.end():oh.start()], DAM_LABELS, month, problems)
    sewers = _rows(text[oh.end():end.start() if end else len(text)], OUTFALL_SEWER_LABELS, month, problems)
    missing = [k for k, _ in DAM_LABELS if k not in dams] + [k for k, _ in OUTFALL_SEWER_LABELS if k not in sewers]
    if missing:
        problems.append(f"{month}: Table 2-7 lacks structure(s) {', '.join(missing)} (a changed table)")
    # notes: the table's own numbered notes, read from the whole section (they print above or below the rows)
    denials = denying_notes(text, month, problems)
    dwo = None
    if (m := DWO.search(" ".join(text.split()))):
        if m.group(1).lower() != "no":
            dwo = {"month": month, "stated": m.group(1).lower(),
                   "outfalls": sorted({x.zfill(3) for x in re.findall(r"(?:CSO|Outfall)\s*#?\s*(\d{3}[A-Za-z]?)",
                                                                       m.group(4) or "")})}
    notes_here = {int(x.group(1)) for x in NOTE.finditer(text)}
    for k, r in list(dams.items()) + list(sewers.items()):
        # a mark on a row with dates must have its note (it may deny one); a 'None' row has no date to deny
        lost = [x for x in r.get("marks", []) if x not in notes_here] if r["dates"] else []
        if lost:
            problems.append(f"{month}: structure {k} carries note mark(s) {', '.join(map(str, lost))} with no such "
                            "note in the section")
    for n in denials:
        if n["dates"]:
            continue
        # a note that names its structure and no date: it denies the one date of the row that carries its mark
        marked = [(k, r) for k, r in list(dams.items()) + list(sewers.items())
                  if k in n["structures"] and n["note"] in r.get("marks", [])]
        if len(marked) == 1 and len(marked[0][1]["dates"]) == 1:
            n["dates"] = [marked[0][1]["dates"][0][1]]
            n["by_mark"] = True
        else:
            problems.append(f"{month}: note {n['note']} says not an overflow to the river and names no date; its "
                            "row cannot be told (no single marked row with one date)")
    if problems:
        return {"status": "unread", "reason": "; ".join(problems)}
    rows, apart = [], []
    for key, r in list(dams.items()) + list(sewers.items()):
        seen: dict[str, int] = {}
        for i, (as_given, d) in enumerate(r["dates"]):
            seen[d] = seen.get(d, 0) + 1
            dur = r["durations"][i] if len(r["durations"]) == len(r["dates"]) else (None, None)
            denied = next((n for n in denials if d in n["dates"] and key in n["structures"]), None)
            row = {"structure": key, "date": d, "date_as_given": as_given, "n": seen[d],
                   "duration_as_given": dur[0], "duration_minutes": dur[1]}
            if d[:7] != month:
                row["date_note"] = f"the date lies outside the month of its table ({month}); kept as DC Water wrote it"
            if denied:
                apart.append({**{k: row[k] for k in ("structure", "date", "duration_as_given")},
                              "note": denied["note"], "basis": f"DC Water's note {denied['note']}: '{denied['denial']}'"
                              + (" (the note names no date; it is marked on this row's one date)"
                                 if denied.get("by_mark") else "")})
            else:
                rows.append(row)
    return {"status": "read", "reason": None, "rows": rows, "set_apart": apart, "dwo": dwo}


TABLE_2_1_ROW = re.compile(r"^\s*(\d{1,3}[a-z]?)\s+.+?\s+((?:0\d\d(?:\s*\(\s*[a-z]\s*\)|[a-zA-Z])?)(?:\s*,\s*0\d\d[a-z]?)*|"
                           r"0\d\d\s*[–-]\s*0\d\d|N/A)\s+(?:\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\b|N/A)", re.M)


def structure_table(pages: list[str]) -> dict[str, str] | None:
    """{structure: outfall} for the dam structures, from the report's own Table 2-1 ('Associated NPDES Outfall'),
    or None when no Table 2-1 page has a text layer. A structure the readable tables disagree on, or list with more
    than one outfall, maps to None (tied to nothing)."""
    seen: dict[str, set] = {}
    found = False
    for p in pages:
        if no_text_layer(p) or not re.search(r"Associated\s+NPDES", p):
            continue
        found = True
        for m in TABLE_2_1_ROW.finditer(p):
            s = m.group(1).upper()
            if s not in STRUCTURE_OUTFALL:
                continue
            of = re.sub(r"\s+|\(|\)", "", m.group(2)).upper()
            seen.setdefault(s, set()).add(of if re.fullmatch(r"0\d\d[A-Z]?", of) else None)
    if not found:
        return None
    return {s: (next(iter(v)) if len(v) == 1 else None) for s, v in seen.items()}


def parse_report(pages: list[str], year: int, q: int) -> dict:
    sections = month_sections(pages)
    blank = sum(1 for p in pages if no_text_layer(p))
    months = {}
    for month in quarter_months(year, q):
        if month in sections and sections[month][1] is None:
            months[month] = {"status": "unread", "page": sections[month][0],
                             "reason": (f"{month}: Table 2-7's section runs onto a page that cannot be read, or its "
                                        "end (section 4) was not found")}
        elif month in sections:
            page, text = sections[month]
            months[month] = {**parse_month(text, month), "page": page}
        else:
            months[month] = {"status": "unread", "page": None,
                             "reason": (f"{month}: Table 2-7 not found on a page with a text layer ({blank} of "
                                        f"{len(pages)} pages have none: their fonts carry no Unicode map)")}
    return {"months": months, "structures": structure_table(pages), "pages": len(pages), "pages_without_text": blank,
            "parser_version": PARSER_VERSION}


# ---------------------------------------------------------------- state and records

def read_quarter(state: dict, entry: dict, content: bytes | None, at: str, error: str | None = None) -> list[str]:
    """Read one copy of a quarter's report into the state; returns the problems (unread months, a failed fetch).
    A month read before is never replaced by a failed read; a month read again replaces its rows under the same ids,
    and a row the new copy no longer lists is kept, marked not_in_revision."""
    key = entry["quarter"]
    reps = state.setdefault("reports", {})
    prev = reps.get(key) or {}
    if error is None and content is not None:
        try:
            parsed = parse_report(pdf_pages(content), entry["year"], entry["q"])
        except UnreadableReport as e:
            error = str(e)
    sha = hashlib.sha256(content).hexdigest() if content is not None else None
    attempt = {"url": entry["url"], "sha256": sha, "read_at": at, "parser_version": PARSER_VERSION, "error": error}
    rep = {**prev, "quarter": key, "year": entry["year"], "q": entry["q"], "url": entry["url"],
           "published": entry.get("published") or prev.get("published"),
           "attempts": (prev.get("attempts") or [])[-9:] + [attempt]}
    months = dict(prev.get("months") or {})
    problems = []
    pend = state.setdefault("pending", {})
    if error is not None:
        problems.append(f"{key}: {error}")
        # a failed fetch or an unreadable copy stays named until a copy of this quarter is read (Astra review P2)
        pend[key] = {"reason": error, "since": (pend.get(key) or {}).get("since") or at, "last_tried": at}
        for m in quarter_months(entry["year"], entry["q"]):
            if (months.get(m) or {}).get("status") != "read":
                months[m] = {"status": "unread", "reason": f"{m}: {error}", "page": None}
    else:
        pend.pop(key, None)
        rep.update(sha256=sha, read_at=at, parser_version=PARSER_VERSION, pages=parsed["pages"],
                   pages_without_text=parsed["pages_without_text"], structures=parsed["structures"])
        for m, new in parsed["months"].items():
            old = months.get(m) or {}
            if new["status"] != "read":
                problems.append(new["reason"])
                if old.get("status") == "read":
                    months[m] = {**old, "reread_failed": {"at": at, "sha256": sha, "reason": new["reason"]}}
                else:
                    months[m] = new
                continue
            ids = {_rid(r) for r in new["rows"]}
            denied = {(a["structure"], a["date"]) for a in new.get("set_apart") or []}
            # a row the new copy no longer lists stays (marked); one the new copy's notes deny does not
            gone = [{**r, "not_in_revision": {"sha256": sha, "read_at": at}} for r in old.get("rows") or []
                    if old.get("status") == "read" and _rid(r) not in ids and (r["structure"], r["date"]) not in denied]
            months[m] = {**new, "rows": new["rows"] + gone, "read_at": at, "sha256": sha}
    rep["months"] = months
    reps[key] = rep
    return problems


def _rid(row: dict) -> str:
    return f"s{row['structure']}-{row['date']}-{row['n']}"


def unread_months(state: dict) -> dict[str, str]:
    out = {}
    for rep in (state.get("reports") or {}).values():
        for m, v in sorted((rep.get("months") or {}).items()):
            if v.get("status") != "read":
                out[m] = v.get("reason") or "not read"
            elif v.get("reread_failed"):
                out[m] = f"a newer copy failed: {v['reread_failed'].get('reason')} (the earlier read is kept)"
    return out


def registry_rows() -> dict[str, dict]:
    out = {}
    for r in common.load_outfall_registry(provisional=False):
        if r.get("npdes_permit") == PERMIT:
            out[common.outfall_key(PERMIT, r.get("outfall"))[1]] = r
    return out


def tie(rep: dict, structure: str) -> tuple[str | None, str]:
    """(registry outfall number or None, the basis): the report's own Table 2-1 when it is readable, else the
    reference transcription (STRUCTURE_OUTFALL); the outfall-sewer structures are in neither and tie to nothing."""
    own = rep.get("structures")
    if structure not in STRUCTURE_OUTFALL:
        return None, "an outfall-sewer structure: Table 2-1 lists no outfall for it, so it is tied to none"
    if own is not None:
        if structure not in own:
            return None, "the report's own Table 2-1 does not list this structure, so it is tied to no outfall"
        if own[structure] is None:
            return None, "the report's own Table 2-1 gives this structure more than one outfall, or none: tied to none"
        return own[structure], "the report's own Table 2-1 ('Associated NPDES Outfall')"
    return STRUCTURE_OUTFALL[structure], (STRUCTURE_OUTFALL_BASIS + "; this report's Table 2-1 has no text layer")


def records(state: dict, registry: dict | None = None) -> list[dict]:
    registry = registry_rows() if registry is None else registry
    out = []
    for key, rep in sorted((state.get("reports") or {}).items()):
        for month, mv in sorted((rep.get("months") or {}).items()):
            if mv.get("status") != "read":
                continue
            for r in mv.get("rows") or []:
                of, basis = tie(rep, r["structure"])
                reg = registry.get(common.outfall_key(PERMIT, of)[1]) if of else None
                slug = (reg or {}).get("water_slug")
                river = RIVER_OF_OUTFALL.get(of) if of else None
                raw = {"quarter": key, "report_url": rep.get("url"), "report_published": rep.get("published"),
                       "report_sha256": mv.get("sha256") or rep.get("sha256"), "month_table": month,
                       "report_page": mv.get("page"), "table": "Table 2-7",
                       "structure": r["structure"], "structure_name": STRUCTURE_NAME.get(r["structure"]),
                       "date_as_given": r.get("date_as_given"),
                       "duration_as_given": r.get("duration_as_given"), "duration_minutes": r.get("duration_minutes"),
                       "duration_basis": "estimated (DC Water's column: 'Estimated Duration of Overflow')",
                       "date_basis": ("the table's Overflow Dates column: a date with no clock time; the start time "
                                      "and the end time are not given"),
                       "outfall_tie": of, "tie_basis": basis,
                       "receiving_water_basis": ("the river DC Water's model results table files the outfall under"
                                                 if river else "no outfall tie: no receiving water is named"),
                       "volume_note": "Table 2-7 gives no volume", "parser_version": rep.get("parser_version"),
                       "time_zone": "America/New_York"}
                if r.get("duration_as_given") is None:
                    raw["duration_note"] = "the table gives this date with no duration"
                for k in ("date_note", "not_in_revision"):
                    if r.get(k):
                        raw[k] = r[k]
                rec = event(
                    source_id=SOURCE_ID, source_record_id=_rid(r), event_type="cso", status="ended",
                    discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER_NAME, npdes_permit=PERMIT,
                    outfall_id=of, outfall_name=(reg or {}).get("outfall_name") if of else None,
                    waterbody_text=river, water_slugs=[slug] if slug else [],
                    water_match="outfall_registry" if slug else "none",
                    lat=(reg or {}).get("lat"), lon=(reg or {}).get("lon"),
                    coord_source="outfall_layer" if reg and reg.get("lat") is not None else None,
                    started_at=r["date"], ended_at=None, time_precision="day",
                    reported_at=None, published_at=rep.get("published"), source_updated_at=None,
                    material=MATERIAL, volume_gal=None, volume_text=None, estimate_flag="unknown",
                    authority=AUTHORITY, source_url=rep.get("url"), raw=raw)
                rec["fetched_at"] = mv.get("read_at") or rep.get("read_at") or rec["fetched_at"]
                out.append(rec)
    return out


def echo_rows(path: Path = ECHO_FILE) -> list[dict]:
    d = read_json(path, {}) or {}
    return [r for r in d.get("records") or [] if isinstance(r, dict) and r.get("npdes_permit") == PERMIT
            and r.get("started_at") and r.get("event_type") in ("cso", "dwo", "unknown") and r.get("outfall_id")]


def link_duplicates(recs: list[dict], rows: list[dict]) -> int:
    """duplicate_of an EPA row of DC0021199 at the same registry outfall (an explicit identifier) whose start falls on
    the same local day; ties to more than one EPA row link nothing."""
    n = 0
    for rec in recs:
        rec["duplicate_of"] = None
        if not rec.get("outfall_id"):
            continue
        mine = common.outfall_key(PERMIT, rec["outfall_id"])
        cands = [r["event_id"] for r in rows
                 if common.outfall_key(PERMIT, r["outfall_id"]) == mine and str(r["started_at"])[:10] == rec["started_at"]]
        if len(cands) == 1:
            rec["duplicate_of"] = cands[0]
            rec["raw"]["duplicate_basis"] = ("EPA's Sewer Overflow and Bypass Event row of the same permit and outfall "
                                             "on the same day is the structured record of this overflow")
            n += 1
    return n


def retained(prev: dict, state: dict) -> list[dict]:
    """The previous events file's records of months the state holds no read of (a missing or emptied state file, a
    month a later copy could not read): never lost, judged month by month (Astra review 2026-11-16 P1)."""
    held = {(k, m) for k, v in (state.get("reports") or {}).items()
            for m, mv in (v.get("months") or {}).items() if mv.get("status") == "read"}
    out = []
    for r in prev.get("records") or []:
        raw = (r or {}).get("raw") or {} if isinstance(r, dict) else {}
        if isinstance(r, dict) and r.get("source_record_id") and (raw.get("quarter"), raw.get("month_table")) not in held:
            out.append({**r, "raw": {**raw, "retained_from": "the previous events file (no read of this month in the state)"}})
    return out


def _age_days(now: str, then: str | None) -> float:
    try:
        a = datetime.fromisoformat(now.replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(then).replace("Z", "+00:00"))
        return (a - b).total_seconds() / 86400
    except (TypeError, ValueError):
        return float("inf")


def due(state: dict, listed: list[dict], now: str, refresh: bool = False) -> list[dict]:
    """The quarters to fetch (see the module docstring)."""
    reps = state.get("reports") or {}
    keep = [e for e in listed if (e["year"], e["q"]) >= FIRST_QUARTER]
    newest = {e["quarter"] for e in sorted(keep, key=lambda e: (e["year"], e["q"]))[-2:]}
    out = []
    for e in sorted(keep, key=lambda e: (e["year"], e["q"])):
        rep = reps.get(e["quarter"])
        if refresh or rep is None or rep.get("url") != e["url"] or (rep.get("parser_version") or 0) < PARSER_VERSION:
            out.append(e)
            continue
        unread = any(m.get("status") != "read" or m.get("reread_failed") for m in (rep.get("months") or {}).values()) \
            or e["quarter"] in (state.get("pending") or {})
        last = max([a.get("read_at") or "" for a in rep.get("attempts") or []] or [""])
        if (e["quarter"] in newest or unread) and _age_days(now, last) >= REREAD_DAYS:
            out.append(e)
    return out


def fetch(url: str, timeout: int = 300) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.content


def read_index(backfill: bool) -> tuple[list[dict], list[dict]]:
    first = fetch(INDEX, 120).decode("utf-8", "replace")
    listed, odd = parse_index(first)
    if not listed:
        raise RuntimeError("the publications list gave no quarterly report (a changed page)")
    if backfill:
        # every page the pages themselves link to, until none links further; a cap reached is a failed read
        last, n = index_pages(first) - 1, 1
        while n <= last:
            if n >= MAX_INDEX_PAGES:
                raise RuntimeError(f"the list has more than {MAX_INDEX_PAGES} pages; not all were read")
            page = fetch(f"{INDEX}&page={n}", 120).decode("utf-8", "replace")
            more, o = parse_index(page)
            listed += more
            odd += o
            last = max(last, index_pages(page) - 1)
            n += 1
    return listed, odd


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = now_iso()
    backfill, refresh = "--backfill" in argv, "--refresh" in argv
    state = read_json(STATE_PATH, {}) or {}
    errors: list[str] = []
    list_failed = False
    if "--file" in argv:
        qk = argv[argv.index("--quarter") + 1]
        y, q = int(qk[:4]), int(qk[-1])
        url = argv[argv.index("--url") + 1] if "--url" in argv else Path(argv[argv.index("--file") + 1]).name
        entry = {"quarter": quarter_key(y, q), "year": y, "q": q, "url": url,
                 "published": argv[argv.index("--published") + 1] if "--published" in argv else None}
        read_quarter(state, entry, Path(argv[argv.index("--file") + 1]).read_bytes(), at)
    elif backfill or refresh or _age_days(at, state.get("index_read_at")) * 24 >= INDEX_EVERY_H:
        try:
            listed, odd = read_index(backfill)
            state["index_read_at"] = at
            state["index"] = {e["quarter"]: {"url": e["url"], "published": e["published"]} for e in listed}
            state["index_odd"] = odd
        except (requests.RequestException, RuntimeError) as e:
            errors.append(f"publications list not read: {type(e).__name__}: {e}")
            listed = []
            list_failed = True
        for e in due(state, listed, at, refresh):
            try:
                content = fetch(e["url"])
                err = None
            except requests.RequestException as ex:
                content, err = None, f"report not fetched: {type(ex).__name__}: {ex}"
            read_quarter(state, e, content, at, err)
    write_json(STATE_PATH, state)
    recs = records(state)
    held = retained(read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}, state)
    recs += held
    dups = link_duplicates(recs, echo_rows())
    unread = unread_months(state)
    errors += [f"{m}: {why}" for m, why in sorted(unread.items())]
    errors += [f"{k}: {v.get('reason')} (since {v.get('since')})" for k, v in sorted((state.get("pending") or {}).items())]
    reps = state.get("reports") or {}
    meta = {"registry_ids": [REGISTRY_ID], "index": INDEX, "first_quarter": quarter_key(*FIRST_QUARTER),
            "quarters_read": {k: {"published": v.get("published"),
                                  "months": {m: mv.get("status") for m, mv in sorted((v.get("months") or {}).items())},
                                  "pages_without_text": v.get("pages_without_text"),
                                  "structure_table": "own" if v.get("structures") is not None else "reference"}
                              for k, v in sorted(reps.items())},
            "unread": unread,
            "pending": {k: {"reason": v.get("reason"), "since": v.get("since")}
                        for k, v in sorted((state.get("pending") or {}).items())},
            "set_apart": [{**a, "quarter": k} for k, v in sorted(reps.items())
                          for mv in (v.get("months") or {}).values() for a in mv.get("set_apart") or []],
            "dry_weather_statements": [mv["dwo"] for v in reps.values() for mv in (v.get("months") or {}).values()
                                       if mv.get("dwo")],
            "not_read": sorted([k for k in (state.get("index") or {}) if (int(k[:4]), int(k[-1])) < FIRST_QUARTER])
                        + [f"{o.get('published')}: {o.get('reason')}" for o in state.get("index_odd") or []],
            "duplicates_of_epa_rows": dups,
            "retained_from_previous_events": len(held),
            "totals_rule": ("the quarter's modeled and metered totals per outfall are not records: each dated "
                            "overflow is one of its outfall's counted occurrences"),
            "cadence": (f"the list at most every {INDEX_EVERY_H} hours; a new report once; the newest two and any "
                        f"report with an unread month again every {REREAD_DAYS} days")}
    path = write_events(SOURCE_ID, recs, ok=not errors, error="; ".join(errors) or None, meta=meta,
                        partial=bool(errors))
    print(f"{SOURCE_ID}: {len(recs)} dated overflows from {len(reps)} quarters ({len(unread)} months unread, "
          f"{dups} linked to EPA rows) -> {path}")
    return backfill_exit(errors, backfill, list_failed, reps, unread, state.get("pending") or {})


def backfill_exit(errors: list[str], backfill: bool, list_failed: bool, reps: dict, unread: dict,
                  pending: dict | None = None) -> int:
    """The exit code. The hourly run: 1 while anything is unread (health false). --backfill: 0 when the list was read
    and the history saved holds at least one month read, the unread months named in the events file (ok false,
    meta.unread) and on this line, so the refresh's one-time backfill loads what can be read; 1 when the read itself
    failed (the list not read, or no month read at all: a changed layout, or a list with no report from
    FIRST_QUARTER on). A quarter whose fetch or read failed after an earlier read is named from meta.pending."""
    read_any = any(mv.get("status") == "read" for v in reps.values() for mv in (v.get("months") or {}).values())
    if backfill and (list_failed or not read_any):
        if not errors:
            print(f"{SOURCE_ID}: backfill read no month", file=sys.stderr)
        return 1
    if not errors:
        return 0
    if backfill:
        print(f"{SOURCE_ID}: backfill saved; not read (named in meta.unread and meta.pending, health false until "
              "read): " + ", ".join(sorted(unread) + sorted(pending or {})), file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
