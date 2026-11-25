"""The City of Houston's monthly sanitary sewer overflow reports and history enrichment -> data/build/events/tx-houston-sso-monthly.json

Source (registry tx-houston-sso-monthly; operator tx-city-of-houston)
  Houston Public Works' consent decree page, https://www.houstonpublicworks.org/wastewater-cd (200 to the pipeline's
  named client, 2026-11-17). Under "Documents" it links one PDF per month, each titled "Monthly SSO Report - <Month
  YYYY>" (April 2021 on; September 2026 the newest on 2026-11-17), at irregular file names (005_monthly_sso_report_
  <month>_<yyyy>.pdf, 055_..._january_2025.pdf, ..._march_29_2024.pdf, ..._october_2024..pdf): the month is read from
  the link's title and the address from the link, never built. The page's yearly "CD Annual Report" files are not
  read here. The reports are made under the City's wastewater consent decree (United States and State of Texas v.
  City of Houston, Civil Action No. 4:18-cv-03368, S.D. Tex., entered 2021): each report's cover letter to EPA Region
  6 cites Paragraph 61 of the decree.

Reading (pypdf, plain text; read on the 33 reports of January 2024 to September 2026)
  - Page 1, the cover letter (officials' names and e-mail addresses), is never read. The table begins on the first
    page carrying the column header (SSO ID, TPDES #, Address, Flow Location, Reached Waters of the US, Est. Volume
    (Gallons), Structure Type, Excursion Cause, Start Date, Start Time, End Date, End Time, Average Flow (GPM),
    Corrective Action), repeated on each table page, and ends at the totals block ("Total Number of SSOs", fish
    kills, notifications to the public, "TWC § 7.251 Report Attached", the City's notes and "Additional Comments").
    The map page after it is never read for records (symbols only); pages after it are read only for the City's
    exhibit of "SSOs subject to Act of God defense - TWC § 7.251" (SSO ID, date, cause, the event claimed).
  - A row begins with its SSO ID and TPDES permit as written: "WQ0010495002", "10495-090" (early 2025), "NON-COH
    (14418-001)" (an overflow from a system that is not the City's, under that permit: the line may break inside
    the parentheses, and the ID may stand on its own line above) or "#N/A". Its cells wrap over several lines; the
    lines are joined and read by the cells' own forms: the Yes or No flag, the volume, the start and end (a date
    and a time each), the average flow and the corrective action. The address and the flow location are told
    apart by the City's flow locations (FLOWS; a flow location not in the list is told by its lower-case letters,
    as the City writes addresses in capitals), the structure type and the cause by the City's structure types
    (STRUCTURES; one not in the list keeps both cells together as written). A row that does not read so is counted
    (meta.rows_not_read), never quoted (it holds a house number), and the report's other rows are kept.
  - Count check: the rows read must number the report's own "Total Number of SSOs"; a difference is named in
    meta.count_mismatch and the feed is not healthy until a rule reads the report whole.
  - Times: "9/1/2026 8:30:00 AM" (2025 on), "1/29/2024 15:00" and "1/31/2026 10:50:00" (24-hour). A time written
    without AM or PM is read on the 24-hour clock only where the same report writes such a time after 12:59 (its
    clock is then known); otherwise, and for a time the change to or from daylight time skips or repeats, the record
    is dated to the day (raw.time_note). Houston is on Central time: America/Chicago, stated as such.
  - The City's notes under the totals are kept: an SSO "erroneously reported in the <Month YYYY> monthly report"
    whose "entry has been voided" is left out of the records (meta.voided, with the City's sentence); "SSO ID#s A and
    B were included in one notification to the public" is kept on those rows (raw.city_note).

Records (one sso record per row)
  - source_record_id the SSO ID; a row repeated in a later report is one record (the newer report's copy).
  - started_at and ended_at the row's start and end, minute precision, Central time; status ended. An end before
    the start is not used (no end; status unknown). No end is ever made up.
  - Volume: "Est. Volume (Gallons)" as written, estimate_flag estimated. The City writes "0" where, in its own words
    under every table, "evidence of an SSO was observed but no active overflow was occurring. Consequently, flow
    rate and total volume loss could not be calculated": such a row has no volume figure (volume_gal null), its
    volume_text says so, and its start and end are the City's as given (raw.volume_note quotes the City).
  - Kept in raw as the City gives them: the TPDES permit (raw.tpdes_permit, normalised to WQ00NNNNNNNN; the permit
    as written in raw.tpdes_as_written), the flow location, "Reached Waters of the US" (raw.reached_waters_of_us; a
    No sets raw.reached_water false, so the status build keeps the record and colours no water, with the City's
    flow location in raw._no_water_reason), the structure type, the excursion cause, the average flow (GPM) and the
    corrective action. published_at: the PDF's Last-Modified date on the City's server (the file's own date;
    raw.report_created keeps the PDF's creation time); fetched_at our read.
  - Place: the table names no water. Nothing is placed by the street (no geocoding) or by the TPDES permit (the
    treatment plant's permit; an overflow in the collection system is not at the plant's outfall): npdes_permit is
    left empty and raw._placement is named_water_only. The street is the Address cell with its house number removed
    (street_of: the leading number, and any other number no route word precedes), as outfall_name and
    raw.location; the town is Houston for the City's own rows. A row is placed on a water only through the
    Commission's record of the same overflow (below) when that record names a water.

One event, one record (link_tceq, the shape of tx_spill_notice_form.link_tceq and al_jefferson_county_soa.link_adem)
  TCEQ's open data (tx-tceq-sso-opendata, the generic reader) carries most of the same overflows months later, with a
  date and no time, no end since mid-2024, and a receiving water on a few. A row and a TCEQ record are one overflow
  when they are of the same sewer system (for the City's own rows any City permit or record: TCEQ often files an
  overflow under another City plant's permit than the table's column; any other row needs its own permit), TCEQ's
  start day is within a day of the row's local start day, the volume is consistent (the same figure; within a factor
  of 2; TCEQ's 0 or 1 gallon placeholder beside the City's "0" or, at the same street, any figure), and both give the
  same street (street_key_of: the name without its type, and the same direction where both give one; TCEQ's street
  is the words after the house number its scrub removed). With no street on either side only the same permit, the
  same day and the same figure above 1 gallon link; a TCEQ address whose street cannot be read never does. Pairs are
  ranked by street, day, permit and volume and taken in rounds: a row and a record each other's best link; n rows and
  n alike records at one street that day are paired in order; any other tie links none. Never linked: records that
  name different waters (build/status.py waters_differ), and a row the City marks as not reaching waters of the US
  when TCEQ's record names a water (both are then shown: err on the side of safety). A TCEQ water text that is a
  segment number ("1007 of the San Jacinto River Basin") is no water's name and is not taken.
  The City's row is the record shown: it has the start and end to the minute, the reached-water flag and the flow
  location; TCEQ's record has days only and, since mid-2024, no end. The TCEQ record is marked duplicate_of the
  row and written back into TCEQ's events file (the Georgia EPD rule, ga_epd_spills.mark_epa_duplicates), with
  raw._duplicate_basis naming the row; the row names the TCEQ record (raw.tceq_record, raw._other_source_record,
  so each record's page links the other) and takes TCEQ's named water (waterbody_text, raw.water_basis) and county.
  Every mark of an earlier run is cleared first, so the links are recomputed each run; the City's events file is
  written before TCEQ's marks. The generic TCEQ reader runs after this module and keeps the marks while its table is
  unchanged (if_changed); a new TCEQ batch is linked in the same hour by ingest.tx_houston_tceq_link (link_only), run
  after the generic readers (Makefile INGEST_SNAPSHOTS). The counts are in meta.tceq_links.


History enrichment (verified live 2026-11-22; one source, not a second event feed)
  RSSO_Package/FeatureServer/0 in the City of Houston GIS organization publishes 29,314 unique EXCURSIONID rows
  since 2018, including private systems. All 4,494 monthly records through October 2026 match that identity. Read
  selected fields and WGS84 geometry in complete, ordered, count-checked pages (maxRecordCount 2000). The numeric
  fields called LATITUDE/LONGITUDE are projected coordinates and must not be used as degrees. Source points are
  rounded to three decimals before persistence. Names, addresses with house numbers and narrative fields are not
  saved. BASIN, WWTP, NOTOBSERVED and GPM remain source evidence; BASIN and WWTP identify sewer infrastructure.
  GPM also supplies average_flow_gpm on history-only records, as the monthly table does on monthly records. The layer has no
  receiving-water-name field. Building backups follow the monthly reader: retain the report, including explicit
  containment, with reached_water false for contained flow; containment never colours a water.
  EXCURSIONID is the existing SSO ID. A monthly row keeps its event ID, reported values and PDF citation; missing
  detail can come from the layer, recorded in raw.history_fields. The selected layer row, point, citation, fetch
  time and layer edit time stay together in raw.history. Layer-only rows use the same source/identity scheme.
  Monthly voids exclude a row even if the layer still lists it. Private-system rows are marked, never attributed
  to the City as operator. An explicit Houston SSO ID in TCEQ's description can link a history-only row without
  assigning an operator. The date, volume, street and water conflict checks still apply.
  Source TOTALVOLLOST is the City's figure, not our calculation: it need not equal rounded GPM times DURATION.
  Zero and null are unknown volume; no end is computed from duration. DURATION is source minutes. Dates are UTC
  epochs of local midnight; separate clocks use an 1899 base date. Decode each epoch in America/Chicago, then
  combine the local day and clock with the event day's DST offset. Missing clocks remain date-only; ambiguous
  clocks remain day precision. A nonmidnight date epoch can itself provide a time if no separate clock exists.
  Cache by layer edit time and count, checked hourly. Failed/incomplete reads keep earlier enrichment and mark
  the source unhealthy. Disappeared history rows retain their original evidence times and a missing-since mark.
  Each history citation queries its own EXCURSIONID. Monthly rows also retain their PDF citation.
  Void notices persist separately from monthly reports and are recovered from previous event metadata.

Privacy: the cover letter is never read; no house number, name, telephone or e-mail is kept: the state file holds the
  parsed rows with streets only, never the PDF or its text; errors name a report and a reason, never a row's text.

Cadence: the index hourly with the refresh (Texas is live). A month never read is read when it is among the NEWEST
  months listed; with --backfill every listed month from BACKFILL_FROM. A month already read is asked again (a
  conditional request) while it is among the NEWEST, and on a backfill whatever its age, and read again only when its
  file changed (a new address, a new Last-Modified date and content) or PARSER_VERSION changed. A month that cannot be
  fetched or read stays pending (meta.pending) and is tried again each run, as does one whose revised copy reads less
  completely than the copy held (which is kept). The run fails (exit 1, the previous records kept) when the index
  cannot be read or lists no monthly report from BACKFILL_FROM; a month pending, rows not read, a count that differs or
  a total not read make the run partial (health false, the records written); --backfill then exits 0 and names them.
Run from pipeline/: python -m ingest.tx_houston_sso_monthly [--backfill] [--link-only]
  [--file report.pdf --month 2026-09 --out x [--tceq tceq-events.json]]
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import io
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import requests

import common
from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, write_events, write_json

SOURCE_ID = "tx-houston-sso-monthly"
INDEX = "https://www.houstonpublicworks.org/wastewater-cd"
HISTORY_LAYER = "https://services.arcgis.com/NummVBqZSIJKUeVR/ArcGIS/rest/services/RSSO_Package/FeatureServer/0"
# Neither LATITUDE/LONGITUDE (projected coordinates despite their names) nor narrative/contact fields are read.
HISTORY_FIELDS = ("OBJECTID", "EXCURSIONID", "ADDRESS", "STARTDATE", "STARTTIME",
                  "ENDDATE", "ENDTIME", "TOTALVOLLOST", "DURATION", "STRUCTURETYPE", "FLOWLOCATION",
                  "SYSTEM", "CAUSE", "BASIN", "WWTP", "NOTOBSERVED", "GPM")
HISTORY_VERSION = 2  # Reread caches whose earlier field selection discarded public source facts.
STATE_PATH = BUILD_DIR / "tx-houston-sso-monthly-state.json"
TCEQ_SOURCE = "tx-tceq-sso-opendata"
TCEQ_EVENTS = EVENTS_DIR / f"{TCEQ_SOURCE}.json"
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
DISCHARGER_ID = "tx-city-of-houston"
DISCHARGER = "City of Houston"
CITY_PREFIX = "WQ0010495"            # the City's TPDES permits (data/dischargers.json tx-city-of-houston)
AUTHORITY = "City of Houston, Houston Public Works, Monthly SSO Report (consent decree, Paragraph 61)"
DECREE = ("Consent decree, United States and State of Texas v. City of Houston, Civil Action No. 4:18-cv-03368 "
          "(S.D. Tex.), Paragraph 61")
BACKFILL_FROM = "2024-01"
NEWEST = 3
PARSER_VERSION = 1       # a change re-reads every month held (due)
LINK_BASIS = "the City of Houston's monthly SSO report row"      # the start of raw._duplicate_basis on TCEQ's record
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
LINK = re.compile(r"""<a\s[^>]*href=["']([^"']+\.pdf)["'][^>]*>(.*?)</a>""", re.I | re.S)
TITLE = re.compile(rf"Monthly\s+SSO\s+Report\s*[-‐‑–—]\s*({'|'.join(MONTHS)})\s+(\d{{4}})\b", re.I)
HEADER = re.compile(r"SSO\s*ID\s+TPDES")
HEADER_END = re.compile(r"Corrective\s+Action\s*$")
# the page footers: the signing envelope's id, and the City's "Additional Comments" (on every table page in 2026)
FOOTER = re.compile(r"^(?:Docu[Ss]ign\s+Envelope\s+ID:|Additional\s+Comments:)", re.I)
TOTALS_START = re.compile(r"^(?:Total\s+Number\s+of|Number\s+of\s+(?:Fish|Notif)|TWC\s*§)", re.I)
TOTAL = re.compile(r"Total\s+Number\s+of\s+SSOs\s*:\s*(\d+)", re.I)
BARE_VALUE = re.compile(r"^(?:\d+\*?|Yes|No)$")
PERMIT = r"WQ\s?\d{10}|\d{5}\s?-\s?\d{2,3}\b|NON-COH\s*\(\s*\d{5}\s*-\s*\d{3}\s*\)?|#N/A"
# a row starts with its SSO ID and its permit, or (a blank permit cell, February 2025) its ID and the address's house
# number ("62541 1234 PANNELL ST"); a line that is an address alone ("12345 MAIN ST", an address cell wrapped) is not one
# an ID before a permit broken over lines ("68785 NON-COH (14418-") starts one too (review 2026-11-17 P1-4)
ROW_START = re.compile(rf"^\d{{5,6}}\s+(?:{PERMIT}|NON-COH\b|#N/A|\d+[A-Z]?\s+[A-Z])")
ID_ONLY = re.compile(r"^\d{5,6}$")
PERMIT_LINE = re.compile(rf"^(?:{PERMIT}|NON-COH\b)")
DATE = r"\d{1,2}\s?/\s?\d{1,2}\s?/\s?\d{4}"
TIME = r"\d{1,2}\s?:\s?\d{2}(?:\s?:\s?\d{2})?(?:\s?[AP]\s?M)?"
ROW_TAIL = (rf"(?P<vol>\d[\d,]*(?:\.\d+)?)\s+(?P<sc>\S.*?)\s+(?P<sd>{DATE})\s+(?P<st>{TIME})\s+(?P<ed>{DATE})\s+"
            rf"(?P<et>{TIME})\s*(?P<gpm>\d[\d,]*(?:\.\d+)?)?\s*(?P<act>\D.*)?$")
ROW = re.compile(rf"^(?P<id>\d{{5,6}})\s+(?:(?P<permit>{PERMIT})\s*)?(?P<af>\S.*?)\s+(?P<flag>Y\s?e\s?s|N\s?o)\s+{ROW_TAIL}")
# the City's flow locations (every one read in 2024-2026), longest first; matched with any spacing
FLOWS = ["Contained On Site, not within 5 ft. of Bayou/Surface Water/Drainage Ditch",
         "Within 5 ft. of Bayou/Surface Water/Drainage Ditch", "Bayou/surface water/drainage ditch",
         "Storm Sewer - contained on site", "Storm Sewer (not contained)", "Storm Sewer - contained", "Contained On Site",
         "Storm Sewer"]
# the City's structure types (every one read in 2024-2026), longest first
STRUCTURES = ["Private Sample Well", "Private Grease Trap", "Private Cleanout", "Private Manhole", "City Cleanout",
              "Service Lateral", "Building Backup", "Gravity Main", "Lift Station", "Force Main", "Manhole"]
# the City's words under every table (its "Additional Comments"), kept as written on each row it reports as "0"
# the City's corrective actions (every one read in 2024-2026 that recurs): pypdf splits their words ("Cleaned and
# D isinfected"); a part that matches one with any spacing is written as the City writes it, any other as read
ACTIONS = ["Cleaned and Disinfected", "Cleared Main Line", "Cleared City Clean Out", "Set Bypass Pump",
           "Cleared Service Lateral", "Post Warning Signs", "Contain All or Portion of Spill", "Cleared Private Line",
           "Returned Spill to Sanitary System", "Issue Public/Media Notification", "Monitor Receiving Waterbody",
           "Spill Response Completion Date"]
ZERO_NOTE = ("Where estimated volume and average flow are reported as \"0\", evidence of an SSO was observed but no active "
             "overflow was occurring. Consequently, flow rate and total volume loss could not be calculated.")
VOID = re.compile(r"SSO\s+ID\s*#?\s*(\d{4,6})\s+was\s+erroneously\s+reported\s+in\s+the\s+([A-Za-z]+\s+\d{4})\s+monthly"
                  r"\s+report[^.]*?\bvoided\b", re.I)
ONE_NOTICE = re.compile(r"SSO\s+ID\s*#?\s*s?\s+((?:\d{4,6}(?:\s*,\s*|\s+and\s+|\s*&\s*)?)+)\s+were\s+included\s+in\s+one\s+"
                        r"notification\s+to\s+the\s+public", re.I)
AOG_LINE = re.compile(r"^(\d{4,6})\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\S.*?)\s*$")
AOG_HEAD = re.compile(r"Act\s+of\s+God\s+Defense", re.I)
# a number after one of these words is a route's, not a house's ("HIGHWAY 6", "FM 1960", "BELTWAY 8")
ROUTE_WORD = re.compile(r"(?i)\b(?:HIGHWAY|HWY|FM|RM|SH|IH|I|US|LOOP|SPUR|BELTWAY|BW|INTERSTATE|ROUTE|RTE|CR|COUNTY\s+ROAD|"
                        r"STATE\s+HIGHWAY|PARK\s+ROAD|PR|EXIT)\s*[-#]?\s*$")
# a token that keeps its number: an ordinal ("18TH") or a route written as one ("I-45", "FM1960")
ORDINAL = re.compile(r"(?i)^\d+(?:ST|ND|RD|TH)[,.]?$")
ROUTE_TOKEN = re.compile(r"(?i)^(?:I|IH|US|SH|FM|RM|HWY|SPUR|LOOP|BW)-?\d+[A-Z]?[,.]?$")
# a unit, suite or apartment designator and its number ("UNIT 5B", "APT 3", "STE 100", "# 12")
UNIT = re.compile(r"(?i)(?:\b(?:UNIT|APT|APARTMENT|STE|SUITE|BLDG|BUILDING|LOT|RM|ROOM)\b|#)\s*#?\s*[\w-]*\d[\w-]*")


class ReadError(ValueError):
    """A report that is not the table this reader knows: no rows are taken from it."""


# ---------------------------------------------------------------- the index

def report_links(page: str, base: str = INDEX) -> dict[str, dict]:
    """{'2026-09': {url, title}} for each monthly SSO report the page links (the first link of a month)."""
    out: dict[str, dict] = {}
    for href, inner in LINK.findall(page):
        title = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        m = TITLE.search(title)
        if not m:
            continue
        key = f"{int(m.group(2)):04d}-{MONTHS.index(m.group(1).lower()) + 1:02d}"
        out.setdefault(key, {"url": urljoin(base, htmllib.unescape(href.strip())).replace("http://", "https://"),
                             "title": title})
    return out


# ---------------------------------------------------------------- the report

def pdf_date(v) -> str | None:
    """"D:20261016083350-05'00'" -> "2026-10-16T08:33:50-05:00"; None when absent or not that form."""
    m = re.fullmatch(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})([+-])(\d{2})'?(\d{2})'?", str(v or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s, sign, oh, om = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}{sign}{oh}:{om}"


def pdf_pages(content: bytes) -> dict:
    """{"pages": [None, text, ...], "created": ISO or None}. Page 1 (the cover letter) is never read; a page pypdf
    cannot read (the map page of some months) is None."""
    import pypdf                                    # pipeline/requirements.txt
    reader = pypdf.PdfReader(io.BytesIO(content))
    pages: list[str | None] = [None]
    for p in reader.pages[1:]:
        try:
            pages.append(p.extract_text() or "")
        except Exception:                           # noqa: BLE001 - a page that cannot be read is named by the parser
            pages.append(None)
    created = None
    try:
        created = pdf_date((reader.metadata or {}).get("/CreationDate"))
    except Exception:                               # noqa: BLE001
        pass
    return {"pages": pages, "created": created}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").replace("‐", "-").replace("‑", "-")
    return " ".join(s.split())


def _loose(text: str) -> re.Pattern:
    """A pattern for the text with any spacing between its characters (pypdf splits words: 'Co ntained', 'Ye s')."""
    return re.compile(r"\s*".join(re.escape(c) for c in text.replace(" ", "")), re.I)


FLOW_RES = [(f, re.compile(rf"(?:^|\s){_loose(f).pattern}$", re.I)) for f in FLOWS]
# a row whose "Reached Waters of the US" cell is blank (May 2026): read only when a flow location of the list closes
# the address, so the volume is never taken from the address
ROW_NO_FLAG = re.compile(rf"^(?P<id>\d{{5,6}})\s+(?:(?P<permit>{PERMIT})\s*)?(?P<af>\S.*?(?:\s|^)"
                         rf"(?:{'|'.join(_loose(f).pattern for f in FLOWS)}))\s+{ROW_TAIL}", re.I)
DATES = re.compile(DATE)
STRUCTURE_RES = [(s, re.compile(rf"^{_loose(s).pattern}(?=\s|$)", re.I)) for s in STRUCTURES]
ACTION_RES = [(a, re.compile(rf"^{_loose(a).pattern}$", re.I)) for a in ACTIONS]


def actions(text: str | None) -> str | None:
    """The corrective-action cell: each part ("; ") as the City writes it where it is one of ACTIONS."""
    parts = []
    for part in re.split(r"\s*;\s*", " ".join((text or "").split())):
        if part:
            parts.append(next((a for a, rx in ACTION_RES if rx.match(part)), part))
    return common.scrub_text("; ".join(parts)) or None


def street_of(cell: str | None) -> str | None:
    """Keep the published Address cell, including house and unit numbers."""
    return _norm(cell or "") or None


def permit_of(cell: str | None) -> tuple[str | None, bool]:
    """(the TPDES permit as WQ00NNNNNNNN or None, whether the City marks the system as not its own). "10495-02" (two
    rows of February 2025) is read as 10495-002, the number with its leading zero."""
    c = re.sub(r"\s", "", cell or "")
    m = re.fullmatch(r"WQ(\d{10})", c)
    if m:
        return f"WQ{m.group(1)}", False
    m = re.search(r"(\d{5})-(\d{2,3})(?!\d)", c)
    if m:
        return f"WQ00{m.group(1)}{int(m.group(2)):03d}", c.upper().startswith("NON-COH")
    return None, c.upper().startswith("NON-COH")


def split_flow(af: str) -> tuple[str | None, str | None, str]:
    """(address, flow location, how) from the cells before the flag."""
    for name, rx in FLOW_RES:
        m = rx.search(af)
        if m:
            return af[:m.start()].strip() or None, name, "list"
    toks = af.split()
    k = next((i for i, w in enumerate(toks) if re.search(r"[a-z]", w)), None)
    if k:
        return " ".join(toks[:k]), " ".join(toks[k:]), "lower case"
    return None, None, "not told apart"


def split_structure(sc: str) -> tuple[str | None, str | None]:
    """(structure type, cause) by the City's structure types; (None, None) when the type is not one of them."""
    for name, rx in STRUCTURE_RES:
        m = rx.match(sc)
        if m:
            return name, (sc[m.end():].strip() or None)
    return None, None


def _clock(t: str) -> tuple[int, int, bool] | None:
    """(hour, minute, whether AM or PM was written); None when not a clock time."""
    t = re.sub(r"\s", "", t).upper()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?([AP]M)?", t)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if mi > 59 or (m.group(3) and int(m.group(3)) > 59):
        return None
    if m.group(4):
        if not 1 <= h <= 12:
            return None
        return h % 12 + (12 if m.group(4) == "PM" else 0), mi, True
    if h > 23:
        return None
    return h, mi, False


def _day(d: str) -> date | None:
    try:
        mo, dd, y = (int(x) for x in re.sub(r"\s", "", d).split("/"))
        return date(y, mo, dd)
    except ValueError:
        return None


def table_lines(pages: list[str | None]) -> tuple[list[str], list[str], int]:
    """(the table's lines, the totals block's lines, the index of the page after the table). ReadError when there
    is no table, a table page cannot be read or has no column header, or no totals block ends it."""
    first = next((i for i, t in enumerate(pages) if i > 0 and t and HEADER.search(t)), None)
    if first is None:
        raise ReadError("no SSO table (no 'SSO ID TPDES' header) in the report")
    lines: list[str] = []
    for i in range(first, len(pages)):
        t = pages[i]
        if t is None:
            raise ReadError(f"table page {i + 1} could not be read")
        if not HEADER.search(t):
            raise ReadError(f"page {i + 1} has no column header and the table has not ended")
        raw = [_norm(x) for x in t.split("\n")]
        end = next((k for k, x in enumerate(raw) if HEADER_END.search(x)), None)
        if end is None:
            raise ReadError(f"page {i + 1}: the column header does not end in 'Corrective Action'")
        body = [x for x in raw[end + 1:] if x and not FOOTER.match(x)]
        stop = next((k for k, x in enumerate(body) if TOTALS_START.match(x)), None)
        if stop is None:
            lines += body
            continue
        lines += body[:stop]
        return lines, body[stop:], i + 1
    raise ReadError("the table has no totals block ('Total Number of SSOs')")


def join_rows(lines: list[str]) -> tuple[list[str], int]:
    """(one string per row, the number of lines before the first row). A row starts at its SSO ID and permit; an ID
    alone on a line followed by a permit line starts one too ("59047" / "NON-COH (14418-" / "001) ...")."""
    rows: list[str] = []
    stray = 0
    k = 0
    while k < len(lines):
        x = lines[k]
        if ID_ONLY.match(x) and k + 1 < len(lines) and PERMIT_LINE.match(lines[k + 1]):
            rows.append(f"{x} {lines[k + 1]}")
            k += 2
            continue
        if ROW_START.match(x):
            rows.append(x)
        elif rows:
            rows[-1] += " " + x
        else:
            stray += 1
        k += 1
    # "NON-COH (14418- 001)": the permit broken over two lines
    rows = [re.sub(r"(NON-COH\s*\(\s*\d{5}\s*-)\s+(\d{3})", r"\1\2", " ".join(r.split())) for r in rows]
    return rows, stray


def totals(block: list[str], lines: list[str]) -> tuple[int | None, list[str]]:
    """(the stated total, the table lines left) from the totals block: "Total Number of SSOs: 89", or (2024's layout)
    the values printed before their labels ("188", "0", "0", "No", then the labels): the first of them."""
    text = " ".join(block)
    m = TOTAL.search(text)
    if m:
        return int(m.group(1)), lines
    k = len(lines)
    while k > 0 and len(lines) - k < 4 and BARE_VALUE.match(lines[k - 1]):
        k -= 1
    vals = lines[k:]
    if vals and vals[0].rstrip("*").isdigit():
        return int(vals[0].rstrip("*")), lines[:k]
    return None, lines


def city_notes(block: list[str], pages_text: str = "") -> dict:
    """The City's notes under the table: voided SSOs, SSOs given one public notification; and its note on '0' (in the
    "Additional Comments" footer of the table pages)."""
    text = " ".join(block)
    out: dict = {"voided": {}, "one_notice": {}, "zero_note": None, "public_notifications": None}
    for m in VOID.finditer(text):
        sent = re.search(rf"[^.]*SSO\s+ID\s*#?\s*{m.group(1)}[^.]*\.(?:[^.]*\bnumber of SSOs\b[^.]*\.)?", text)
        out["voided"][m.group(1)] = {"reported_in": m.group(2),
                                     "note": common.scrub_text(" ".join((sent.group(0) if sent else m.group(0)).split()))}
    for m in ONE_NOTICE.finditer(text):
        for i in re.findall(r"\d{4,6}", m.group(1)):
            out["one_notice"][i] = common.scrub_text(" ".join(m.group(0).split())) + "."
    if re.search(r"evidence\s+of\s+an\s+SSO\s+was\s+obser\s?ved\s+but\s+no\s+active\s+overflow", f"{text} {pages_text}", re.I):
        out["zero_note"] = ZERO_NOTE
    m = re.search(r"Notifications\s+to\s+the\s+Public\s*:\s*(\d+)", text, re.I)
    if m:
        out["public_notifications"] = int(m.group(1))
    return out


def act_of_god(pages: list[str | None], after: int) -> dict[str, dict]:
    """{SSO ID: {date, as_written}} from the City's exhibit of SSOs subject to the act-of-God defense (TWC § 7.251)."""
    out: dict[str, dict] = {}
    for t in pages[after:]:
        if not t or not AOG_HEAD.search(t):
            continue
        for x in t.split("\n"):
            m = AOG_LINE.match(_norm(x))
            if m:
                out.setdefault(m.group(1), {"date": m.group(2), "as_written": common.scrub_text(m.group(3))})
    return out


def parse_row(s: str) -> dict | None:
    """One row's cells (house number removed), or None when the row does not read."""
    if len(DATES.findall(s)) != 2:
        return None          # two rows run together (a row start not seen): neither is read, never half of one
    m = ROW.match(s) or ROW_NO_FLAG.match(s)
    if not m:
        return None
    permit, non_city = permit_of(m.group("permit"))
    addr, flow, how = split_flow(m.group("af").strip())
    sd, ed = _day(m.group("sd")), _day(m.group("ed"))
    st, et = _clock(m.group("st")), _clock(m.group("et"))
    if sd is None or ed is None or st is None or et is None:
        return None
    sc = " ".join(m.group("sc").split())
    structure, cause = split_structure(sc)
    # no cause, structure or action the City writes holds a digit: one that does holds another row's text (an address,
    # an SSO id) joined to this row; the row is not read, never kept with it (review 2026-11-17 P1-4)
    if re.search(r"\d", f"{sc} {m.group('act') or ''}") or (how != "list" and re.search(r"\d", flow or "")):
        return None
    flag = re.sub(r"\s", "", m.groupdict().get("flag") or "") or None
    row = {"sso_id": m.group("id"), "tpdes_permit": permit,
           "tpdes_as_written": " ".join((m.group("permit") or "").split()) or None,
           "non_city": non_city, "street": street_of(addr) if addr else None, "flow_location": flow,
           "reached": flag, "volume": m.group("vol"), "structure_type": structure,
           "cause": common.scrub_text(cause) if cause else None,
           "start_day": sd.isoformat(), "start_clock": [st[0], st[1]], "start_ampm": st[2],
           "end_day": ed.isoformat(), "end_clock": [et[0], et[1]], "end_ampm": et[2],
           "start_as_written": f"{re.sub(chr(32), '', m.group('sd'))} {' '.join(m.group('st').split())}",
           "end_as_written": f"{re.sub(chr(32), '', m.group('ed'))} {' '.join(m.group('et').split())}",
           "average_flow_gpm": m.group("gpm"),
           "corrective_action": actions(m.group("act"))}
    if structure is None:
        row["structure_and_cause_as_written"] = common.scrub_text(sc)
    if how != "list":
        row["flow_location_read_by"] = how
    if not addr:
        row["street_not_read"] = True
    return row


def parse_report(pages: list[str | None]) -> dict:
    """{rows, not_read, stray_lines, total_stated, notes, act_of_god, clock24}. ReadError when there is no table."""
    lines, block, after = table_lines(pages)
    total, lines = totals(block, lines)
    raw_rows, stray = join_rows(lines)
    rows, bad = [], 0
    for s in raw_rows:
        r = parse_row(s)
        if r is None:
            bad += 1
        else:
            rows.append(r)
    if not rows:
        raise ReadError(f"the SSO table's {len(raw_rows)} rows read as no row")
    # the 24-hour clock is known when the report writes a time without AM or PM after 12:59
    clock24 = any((not r["start_ampm"] and r["start_clock"][0] >= 13) or (not r["end_ampm"] and r["end_clock"][0] >= 13)
                  for r in rows)
    pages_text = " ".join(_norm(t) for t in pages[1:after] if t)
    return {"rows": rows, "not_read": bad, "stray_lines": stray, "total_stated": total,
            "notes": city_notes(block, pages_text),
            "act_of_god": act_of_god(pages, after), "clock24": clock24, "parser_version": PARSER_VERSION}


# ---------------------------------------------------------------- records

_HOLDERS: dict[str, tuple[str, str]] | None = None


def permit_holders() -> dict[str, tuple[str, str]]:
    """{TPDES permit: (operator id, name)} from data/dischargers.json: its state permits, and the federal permits that
    TCEQ's crosswalk (data/reference/tx-tceq-permits.json) gives for a TPDES number."""
    global _HOLDERS
    if _HOLDERS is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
        rows = rows if isinstance(rows, list) else []
        wq = (read_json(DATA_DIR / "reference" / "tx-tceq-permits.json", {}) or {}).get("wq_to_npdes") or {}
        by_npdes = {}
        out: dict[str, tuple[str, str]] = {}
        for d in rows:
            if not isinstance(d, dict) or d.get("state") not in (None, "TX") or not d.get("id"):
                continue
            for p in d.get("state_permits") or []:
                out.setdefault(str(p), (d["id"], d.get("name") or d["id"]))
            for p in d.get("npdes_permits") or []:
                by_npdes.setdefault(str(p), (d["id"], d.get("name") or d["id"]))
        for w, ns in wq.items():
            for n in ns or []:
                if n in by_npdes:
                    out.setdefault(w, by_npdes[n])
        _HOLDERS = out
    return _HOLDERS


def holder_of(permit: str | None, non_city: bool) -> tuple[str | None, str | None]:
    """(operator id, name) of the system the row's permit names: the City for its own permits (WQ0010495...) unless
    the City marks the row NON-COH; else the permit's holder in the registry; (None, None) when not known."""
    if permit and permit.startswith(CITY_PREFIX) and not non_city:
        return DISCHARGER_ID, DISCHARGER
    h = permit_holders().get(permit or "")
    if h and h[0] == DISCHARGER_ID and non_city:
        return None, None
    return h if h else (None, None)


def _local(d: date, h: int, mi: int) -> datetime | None:
    """The instant of a wall-clock time in Houston, or None when the change to or from daylight time skips it or
    makes it happen twice."""
    a = datetime(d.year, d.month, d.day, h, mi, tzinfo=TZ, fold=0)
    if a.utcoffset() != a.replace(fold=1).utcoffset():
        return None
    back = a.astimezone(UTC).astimezone(TZ)
    return a if (back.hour, back.minute) == (h, mi) else None


def _when(r: dict, which: str, clock24: bool) -> tuple[datetime | None, str | None]:
    """(the instant, or None with the reason) of the row's start or end."""
    d = date.fromisoformat(r[f"{which}_day"])
    h, mi = r[f"{which}_clock"]
    if not r[f"{which}_ampm"] and not clock24:
        return None, (f"the {which} time is written '{r[f'{which}_as_written']}' with no AM or PM in a report whose "
                      "clock is not known")
    t = _local(d, h, mi)
    if t is None:
        return None, (f"the {which} time '{r[f'{which}_as_written']}' falls in the hour the change to or from daylight "
                      "time skips or repeats")
    return t, None


def _gallons(v: str) -> int | None:
    try:
        f = float(v.replace(",", ""))
    except ValueError:
        return None
    return int(round(f)) if f > 0 else None


def to_records(month: str, rep: dict) -> list[dict]:
    out = []
    notes = rep.get("notes") or {}
    aog = rep.get("act_of_god") or {}
    for r in rep["rows"]:
        st, why_st = _when(r, "start", rep.get("clock24", False))
        en, why_en = _when(r, "end", rep.get("clock24", False)) if st else (None, None)
        raw = {"state": "TX", "time_zone": TZ_NAME, "report_month": month, "report_url": rep.get("url"),
               "report_title": rep.get("title"), "report_sha256": rep.get("sha256"),
               "report_created": rep.get("created"), "report_last_modified": rep.get("last_modified"),
               "sso_id": r["sso_id"], "tpdes_permit": r["tpdes_permit"], "tpdes_as_written": r["tpdes_as_written"],
               "location": r.get("street"), "flow_location": r.get("flow_location"),
               "reached_waters_of_us": r["reached"], "volume_as_written": r["volume"],
               "structure_type": r.get("structure_type"), "cause": r.get("cause"),
               "start_as_written": r["start_as_written"], "end_as_written": r["end_as_written"],
               "average_flow_gpm": r.get("average_flow_gpm"), "corrective_action": r.get("corrective_action"),
               "legal_basis": DECREE, "_placement": "named_water_only",
               "place_note": ("the City's table gives a street address; the house number is removed and no point is "
                              "taken from the street"),
               "published_basis": "the report PDF's Last-Modified date on the City's server",
               "timezone_note": "the table writes local times with no zone; Houston is on Central time (America/Chicago)",
               "parser_version": rep.get("parser_version")}
        if r.get("structure_and_cause_as_written"):
            raw["structure_and_cause_as_written"] = r["structure_and_cause_as_written"]
        if r.get("flow_location_read_by"):
            raw["flow_location_note"] = "the flow location is not one of the City's usual wordings; read as written"
        did, dname = holder_of(r["tpdes_permit"], r["non_city"])
        if r["non_city"]:
            raw["system_note"] = (f"the City's table marks this overflow NON-COH, under permit {r['tpdes_permit']}: a "
                                  "sewer system that is not the City's" + (f"; the permit is {dname}'s" if dname else ""))
        elif did and did != DISCHARGER_ID:
            raw["system_note"] = f"the City's table lists this overflow under permit {r['tpdes_permit']}, {dname}'s"
        elif not r["tpdes_permit"]:
            raw["system_note"] = "the City's table gives no permit for this overflow" + (
                f" (written \"{r['tpdes_as_written']}\")" if r.get("tpdes_as_written") else "")
        if r.get("tpdes_as_written") and re.fullmatch(r"\d{5}\s?-\s?\d{2}", r["tpdes_as_written"]):
            raw["tpdes_note"] = f"written {r['tpdes_as_written']}; read as {r['tpdes_permit']}"
        if did == DISCHARGER_ID:
            raw["city"] = "Houston"
        if r["reached"] is None:
            raw["reached_waters_note"] = "the City's table leaves \"Reached Waters of the US\" blank for this overflow"
        if r["reached"] == "No":
            raw["reached_water"] = False
            raw["_no_water_reason"] = ("the City's table says the overflow did not reach waters of the United States"
                                       + (f" (flow location: {r['flow_location']})" if r.get("flow_location") else ""))
        elif r["reached"] == "Yes":
            raw["reached_water"] = True
        if r["sso_id"] in (notes.get("one_notice") or {}):
            raw["city_note"] = notes["one_notice"][r["sso_id"]]
        if r["sso_id"] in aog:
            raw["act_of_god_defense"] = {**aog[r["sso_id"]], "basis": (
                "the City's exhibit of SSOs subject to the act-of-God defense under Texas Water Code § 7.251")}
        gal = _gallons(r["volume"])
        if gal is None:
            raw["volume_note"] = ZERO_NOTE
            vtext = "reported as 0 gallons: no active overflow when observed; volume not calculated"
        else:
            vtext = f"{r['volume']} gallons (estimated)"
        prec, started, ended, status = "minute", None, None, "unknown"
        if st is None:
            prec, started = "day", r["start_day"]
            raw["time_note"] = f"{why_st}: the record is dated to the day"
        else:
            started = st.isoformat()
            if en is None:
                raw["end_note"] = f"{why_en}: no end is given"
            elif en < st:
                raw["end_note"] = (f"the end written ({r['end_as_written']}) is before the start "
                                   f"({r['start_as_written']}): no end is given")
            else:
                ended, status = en.isoformat(), "ended"
                raw["ended_at_precision"] = "minute"
        out.append(event(
            source_id=SOURCE_ID, source_record_id=r["sso_id"], event_type="sso", status=status,
            discharger_id=did, discharger_name=dname, npdes_permit=None,
            outfall_name=r.get("street"), waterbody_text=None, water_slugs=[], water_match="none",
            started_at=started, ended_at=ended, time_precision=prec,
            reported_at=None, published_at=rep.get("last_modified"), source_updated_at=None,
            fetched_at=rep.get("read_at") or now_iso(), material="untreated sewage", volume_gal=gal,
            volume_text=vtext, estimate_flag="estimated" if gal is not None else "unknown",
            authority=AUTHORITY, source_url=rep.get("url"), raw=raw))
    return out


def build(state: dict) -> tuple[list[dict], dict]:
    """(the records of every report held, newest report's copy of a repeated SSO; the voided ones left out)."""
    by_id: dict[str, dict] = {}
    voided: dict[str, dict] = dict(state.get("voided") or {})
    for month, rep in sorted((state.get("reports") or {}).items()):
        for r in to_records(month, rep):
            by_id[r["event_id"]] = r
        for sid, v in ((rep.get("notes") or {}).get("voided") or {}).items():
            voided[sid] = {**v, "noted_in": month}
    for sid in voided:
        by_id.pop(f"{SOURCE_ID}:{sid}", None)
    recs = sorted(by_id.values(), key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, voided


def retained(prev: dict, state: dict, recs: list[dict], voided: dict) -> list[dict]:
    """The previous events file's records of reports with no copy in the state (a lost or emptied state file): kept,
    so a lost state never drops an earlier record; a record the City voided is not kept."""
    have = set(state.get("reports") or {})
    ids = {r["event_id"] for r in recs}
    out = []
    for r in prev.get("records") or []:
        raw = (r.get("raw") or {}) if isinstance(r, dict) else {}
        if not isinstance(r, dict) or r.get("event_id") in ids or raw.get("report_month") in have \
                or str(raw.get("sso_id")) in voided:
            continue
        out.append({**r, "raw": {**raw, "retained_from": "the previous events file (no copy of this report in the state)"}})
    return out


# ---------------------------------------------------------------- one event, one record

# the words after a house number TCEQ's scrub removed; never after "SSO ID#" (the City's id, scrubbed as a number)
AFTER_NUMBER = re.compile(r"(?<!#)(?<!# )(?<!ID )" + r"(?:" + re.escape(common.HOUSE_NUMBER_REMOVED) + r"|\b\d{1,6}(?:-[A-Z])?)\s+([^(/,;:]*)")
# a street ends where a sentence goes on ("TARTAN was caused by", "Sage Park Ln had a discharge")
SENTENCE_WORDS = {"was", "were", "is", "had", "has", "caused", "discharged", "discharge", "overflowed", "on", "in", "at",
                  "due", "from", "near", "and", "the", "of", "to", "by", "for", "with", "which", "that", "an", "a"}
NOT_A_STREET = re.compile(r"(?i)^(?:manhole|cleanout|city|private|service|gravity|force|lift|non-observed|storm|contained|"
                          r"sso\b|gallons?)\b")
MATCH_PAD_DAYS = 1
# TCEQ's water text that is a segment number of a basin ("1007 of the San Jacinto River Basin", "Segment 1007 of San
# Jacinto River Basin"): no water's name, and nothing places it; it is kept with the link, never taken as the water
SEGMENT_TEXT = re.compile(r"(?i)^\W*(?:no\.?\s*)?(?:segment\s*(?:no\.?|number|#)?\s*)?\d{3,4}[a-z]{0,2}\s+(?:of|in)\s+"
                          r"(?:the\s+)?[a-z\s-]+basin\W*$")


def tceq_street(t: dict) -> tuple[tuple | None, bool]:
    """(the street TCEQ's record gives as street_key_of's key, whether it gives an address at all): the words after the
    house number its scrub removed, in its source ("Manhole at [house number removed] Kenwood Ln", "[house number
    removed] LEELAND STREET, HOUSTON, TX ...", "[house number removed] SAM HOUSTON 77... (...)/Manhole"), else in its
    description; up to a ZIP code, a parenthesis, a slash, a comma or a sentence word, in any case (review 2026-11-17
    P1-2: "alpine st"). An address whose street cannot be read gives (None, True): never the weaker match."""
    raw = t.get("raw") or {}
    had = False
    for text in (str(t.get("outfall_name") or ""), str((raw.get("row") or {}).get("incident_description") or "")):
        for m in AFTER_NUMBER.finditer(text):
            had = True
            c = re.split(r"\s\d{5}(?:-\d{4})?\b", m.group(1))[0]
            c = re.sub(r"(?i)\bHOUSTON\s*,?\s*TX\b.*$", " ", c)
            words = []
            for w in c.split():
                if w.lower().strip(".") in SENTENCE_WORDS or len(words) == 6:
                    break
                words.append(w)
            c = " ".join(words)
            if not c or NOT_A_STREET.match(c):
                continue
            k = street_key_of(street_of(c))
            if k:
                return k, True
    return None, had


def _tceq_day(t: dict) -> date | None:
    try:
        return date.fromisoformat(str(t.get("started_at") or "")[:10])
    except ValueError:
        return None


def _volume_ok(r: dict, t: dict) -> tuple[bool, int]:
    """(consistent, rank: 0 the same figure, 1 within a factor of 2 or not given). The City's "0" (no figure) meets
    TCEQ's placeholder figures for such rows (0 and 1 gallon) or none."""
    mine = r.get("volume_gal")
    theirs = t.get("volume_gal")
    if theirs is None:
        return True, 1
    if mine is None:
        return theirs <= 1, 0
    if theirs == mine:
        return True, 0
    if theirs <= 1:                      # TCEQ's placeholder (0 or 1 gallon) beside the City's figure
        return True, 2
    return mine / 2 <= theirs <= mine * 2, 1


STREET_TYPES = {"ST", "STREET", "DR", "DRIVE", "LN", "LANE", "RD", "ROAD", "AVE", "AV", "AVENUE", "BLVD", "BOULEVARD",
                "CT", "COURT", "PKWY", "PARKWAY", "WAY", "CIR", "CIRCLE", "PL", "PLACE", "TRL", "TRAIL", "FWY", "FREEWAY",
                "TER", "TERRACE", "CV", "COVE", "XING", "CROSSING", "SQ", "EXPY", "BND", "BEND", "PT", "POINT"}
DIRECTIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}


def street_key_of(street: str | None) -> tuple[str, frozenset] | None:
    """(the street's name, its direction words) for comparison: letters and digits, without its type at the end
    ("SAM HOUSTON PKWY", "SAM HOUSTON" -> "SAMHOUSTON") and its direction at either end ("N WAYSIDE DR" -> "WAYSIDE",
    {"N"}). None when no name is left."""
    toks = re.findall(r"[A-Z0-9]+", str(street or "").upper().replace(common.HOUSE_NUMBER_REMOVED.upper(), " "))
    if toks and toks[0].isdigit():
        toks.pop(0)  # comparison only; the source address stays complete
    dirs = set()
    while toks and toks[-1] in STREET_TYPES | DIRECTIONS and len(toks) > 1:
        if toks[-1] in DIRECTIONS:
            dirs.add(toks[-1][0])
        toks.pop()
    while toks and toks[0] in DIRECTIONS and len(toks) > 1:
        dirs.add(toks.pop(0)[0])
    name = "".join(toks)
    return (name, frozenset(dirs)) if name and re.search(r"[A-Z]{3}", name) else None


def _same_street(a: tuple | None, b: tuple | None) -> bool | None:
    """True or False when both give a street: the same name (review 2026-11-17 P1-1: PINE is not ALPINE), and the same
    direction where both give one; None when either gives none."""
    if not a or not b:
        return None
    return a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1])


def _same_system(r: dict, t: dict) -> tuple[bool, bool]:
    """(the same sewer system, the same permit). The City files many overflows with TCEQ under another of its plants'
    permits than the table's TPDES column gives (on 2025-01-07 a 2,832-gallon overflow is WQ0010495037 in the table and
    WQ0010495090 in TCEQ's), so for the City's own rows the City's records are the system; another permit's row needs
    that permit."""
    permits = (t.get("raw") or {}).get("state_permits") or []
    same_permit = bool(r["raw"].get("tpdes_permit")) and r["raw"]["tpdes_permit"] in permits
    if r.get("discharger_id") == DISCHARGER_ID:
        return same_permit or t.get("discharger_id") == DISCHARGER_ID or any(
            str(p).startswith(CITY_PREFIX) for p in permits), same_permit
    return same_permit, same_permit


def _link(r: dict, t: dict, rank: tuple, n: int, counts: Counter, S) -> int:
    """Link one row and one TCEQ record (link_tceq), unless they name different waters or the City says no water was
    reached where TCEQ names one; returns 1 when linked."""
    rid, tid = r["event_id"], t["event_id"]
    if S.waters_differ(r, t):
        counts["not linked: the two name different waters"] += 1
        return 0
    named = t.get("waterbody_text") if not (S.no_water_flag(t) or S.no_receiving_water(t)) else None
    segment = bool(named and SEGMENT_TEXT.match(named))
    if segment:
        named = None
    if r["raw"].get("reached_water") is False and named:
        counts["not linked: the City says no water was reached, TCEQ names one"] += 1
        return 0
    how = ["explicit Houston SSO ID" if rank[0] == -1 else
           "same " + ("permit" if rank[2] == 0 else "City system"),
           "same start day" if rank[1] == 0 else "start a day apart"]
    how += ["same street"] if rank[0] == 0 else []
    how += [{0: "same volume", 1: "consistent volume", 2: "TCEQ gives 0 or 1 gallon"}[rank[3]]]
    if n > 1:
        how += [f"one of {n} alike overflows at that street that day, paired in order"]
    r["raw"]["tceq_record"] = tid
    r["raw"]["_other_source_record"] = tid
    r["raw"]["tceq_match"] = {"basis": ", ".join(how), "tceq_volume_gal": t.get("volume_gal"),
                              "tceq_received": t.get("reported_at"),
                              "tceq_permits": (t.get("raw") or {}).get("state_permits")}
    if segment:
        r["raw"]["tceq_match"]["tceq_water_text"] = t.get("waterbody_text")     # a segment number: not a water's name
    county = (t.get("raw") or {}).get("county")
    if county:
        r["raw"]["county"] = county
    if named:
        r["waterbody_text"] = named
        r["raw"]["water_basis"] = (f"the water TCEQ's record of the same overflow ({tid}) names; the City's table "
                                   "names none")
    t["duplicate_of"] = rid
    basis = LINK_BASIS if r["raw"].get("report_month") else "the City of Houston's SSO history row"
    t.setdefault("raw", {})["_duplicate_basis"] = (
        f"{basis} {rid} (SSO ID {r['raw']['sso_id']}) is the same overflow ({', '.join(how)}); the City's "
        "reported row is shown")
    counts["linked"] += 1
    counts["linked, with a TCEQ water"] += bool(named)
    return 1


def link_tceq(records: list[dict], tceq: list[dict]) -> Counter:
    """Mark each TCEQ record of the same overflow duplicate_of the City's row (module docstring); both lists change in
    place (TCEQ's marks of an earlier run are cleared first). Returns the counts.
    A pair: the same system (_same_system), TCEQ's start day within MATCH_PAD_DAYS of the row's local start day, a
    consistent volume, and the same street where both give one; with no street on either side, only the same permit,
    the same day and the same figure above 1 gallon. Ranked by street, day, permit and volume; each row and each TCEQ
    record once (the rounds below); a tie at the best rank links neither, unless the tied records are alike."""
    from build import status as S          # here, not at the top: the status build's tests of a water and of none
    counts: Counter = Counter()
    for t in tceq:
        if str((t.get("raw") or {}).get("_duplicate_basis") or "").startswith((LINK_BASIS, "the City of Houston's SSO history row")):
            t["duplicate_of"] = None
            t["raw"].pop("_duplicate_basis", None)
    for r in records:                       # a record kept from the previous file carries the last run's link
        if r["raw"].pop("water_basis", None):
            r["waterbody_text"] = None
        for k in ("tceq_record", "_other_source_record", "tceq_match", "county"):
            r["raw"].pop(k, None)
    by_day: dict[date, list[dict]] = {}
    for t in tceq:
        d = _tceq_day(t)
        if d and not t.get("duplicate_of") and t.get("event_type") == "sso":
            by_day.setdefault(d, []).append(t)
    keys = {}
    pairs = []
    for r in records:
        if not r.get("started_at"):
            continue
        d0 = date.fromisoformat(r["started_at"][:10])
        mine = street_key_of(r["raw"].get("location"))
        for k in range(-MATCH_PAD_DAYS, MATCH_PAD_DAYS + 1):
            for t in by_day.get(date.fromordinal(d0.toordinal() + k), []):
                references = (t.get("raw") or {}).get("houston_sso_ids") or []
                exact = references == [str(r["source_record_id"])]
                # An explicit reference cannot be overridden by a fuzzy candidate or an ambiguous ID list.
                if references and not exact:
                    continue
                system, permit = _same_system(r, t)
                if not system and (not exact or r["raw"].get("tpdes_permit") or r.get("discharger_id")):
                    continue
                ok, vrank = _volume_ok(r, t)
                if not ok:
                    continue
                if t["event_id"] not in keys:
                    keys[t["event_id"]] = tceq_street(t)
                theirs, had = keys[t["event_id"]]
                if theirs is None and had:
                    continue            # an address that could not be read: never the weaker match (review P1-2)
                same = _same_street(mine, theirs)
                if same is False:
                    continue
                if same is None and not exact and not (permit and k == 0 and vrank == 0 and (r.get("volume_gal") or 0) > 1):
                    continue
                pairs.append(((-1 if exact else 0 if same else 1, abs(k), 0 if permit else 1, vrank), r["event_id"], t["event_id"]))
    # rounds: the pairs at the best rank of both their row and their TCEQ record (among those not yet linked), grouped
    # (a row and a record joined by such a pair). A group of one row and one record links them. A group of n rows and n
    # records all paired with each other at one rank (n overflows at one street that day, each in both lists) whose
    # TCEQ records are alike (the same figure and water) links them in order: either order shows the same records. Any
    # other group links none this round; the rows and records left are ranked again, until a round links none.
    by_r = {r["event_id"]: r for r in records}
    by_t = {t["event_id"]: t for t in tceq}
    done: set[str] = set()
    while True:
        live = [p for p in pairs if p[1] not in done and p[2] not in done]
        best_r: dict[str, tuple] = {}
        best_t: dict[str, tuple] = {}
        for rank, rid, tid in live:
            best_r[rid] = min(best_r.get(rid, rank), rank)
            best_t[tid] = min(best_t.get(tid, rank), rank)
        top = [(rank, rid, tid) for rank, rid, tid in live if rank == best_r[rid] == best_t[tid]]
        parent: dict[str, str] = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for _, rid, tid in top:
            parent[find("r" + rid)] = find("t" + tid)
        groups: dict[str, list] = {}
        for p in top:
            groups.setdefault(find("r" + p[1]), []).append(p)
        linked_now, ties = 0, 0
        for g in groups.values():
            rids = sorted({p[1] for p in g}, key=lambda i: (by_r[i]["started_at"], i))
            tids = sorted({p[2] for p in g}, key=lambda i: (str(by_t[i].get("source_record_id")), i))
            alike = len({(by_t[i].get("volume_gal"), by_t[i].get("waterbody_text")) for i in tids}) == 1
            if len(rids) != len(tids) or len(g) != len(rids) * len(tids) or len({p[0] for p in g}) != 1 or not alike:
                ties += len(rids)
                continue
            for rid, tid in zip(rids, tids):
                done.update((rid, tid))       # tried once: linked, or kept apart (different waters, no water)
                linked_now += _link(by_r[rid], by_t[tid], g[0][0], len(rids), counts, S)
        if not linked_now:
            if ties:
                counts["not linked: two equally good candidates"] += ties
            break
    counts["rows without a TCEQ record"] = sum(1 for r in records if not r["raw"].get("tceq_record"))
    return counts


# ---------------------------------------------------------------- history enrichment (same source and SSO identity)

def _number(v):
    try:
        n = float(v) if v is not None and not isinstance(v, bool) else None
        return n if n is not None and math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def history_id(a: dict) -> str:
    n = _number(a.get("EXCURSIONID"))
    if n is None or n <= 0 or not n.is_integer():
        raise ReadError("history row has no valid excursion identity")
    return str(int(n))


def safe_history_feature(f: dict) -> dict:
    """Only selected fields, streets without house numbers, and source geometry rounded to about 100 m."""
    from ingest.generic.fieldmap import scrub_strict_names
    a = {k: v for k, v in (f.get("attributes") or {}).items() if k in HISTORY_FIELDS}
    history_id(a)
    for k, v in a.items():
        if isinstance(v, str):
            a[k] = scrub_strict_names(v)
    if a.get("ADDRESS"):
        a["ADDRESS"] = street_of(a["ADDRESS"])
    g = f.get("geometry") or {}
    x, y = _number(g.get("x")), _number(g.get("y"))
    # A service returning its projected geometry despite outSR must not become a geographic point.
    point = {"x": x, "y": y} if (
        x is not None and y is not None and -97 < x < -94 and 28 < y < 31) else None
    return {"attributes": a, "geometry": point}


def read_history(held: dict, at: str, get) -> dict:
    """Atomic, count-checked offset paging. An unchanged version needs only metadata and count requests.

    A changed layer is read completely before replacing state. Previously observed rows that disappear are
    retained with their original observation time; monthly void notices still exclude them at merge time.
    """
    def request(path, **params):
        response = get(path + "?" + urlencode({"f": "json", **params}))
        response.raise_for_status()
        d = response.json()
        if not isinstance(d, dict) or "error" in d:
            raise ReadError("history service did not return a usable response")
        return d

    meta = request(HISTORY_LAYER)
    names = {f.get("name") for f in meta.get("fields") or []}
    if not set(HISTORY_FIELDS) <= names:
        raise ReadError("history layer is missing required fields")
    if not (meta.get("advancedQueryCapabilities") or {}).get("supportsPagination"):
        raise ReadError("history layer does not support complete offset paging")
    size = min(int(meta.get("maxRecordCount") or 0), 2000)
    if size < 1:
        raise ReadError("history layer has no valid page size")
    query = HISTORY_LAYER + "/query"
    count = request(query, where="1=1", returnCountOnly="true").get("count")
    if not isinstance(count, int) or count <= 0:
        raise ReadError("history layer has no readable count")
    edit = (meta.get("editingInfo") or {}).get("lastEditDate")
    if edit is not None and held.get("last_edit") == edit and held.get("current_count") == count \
            and held.get("parser_version") == HISTORY_VERSION and held.get("features"):
        return {**held, "checked_at": at, "features": [
            {**f, "attributes": {k: v for k, v in f["attributes"].items() if k in HISTORY_FIELDS}}
            for f in held["features"]]}
    features, ids, oids = [], set(), set()
    last_oid = -1
    while len(features) < count:
        d = request(query, where="1=1", outFields=",".join(HISTORY_FIELDS), returnGeometry="true", outSR=4326,
                    orderByFields="OBJECTID ASC", resultOffset=len(features), resultRecordCount=size)
        page = d.get("features")
        if not isinstance(page, list) or not page:
            raise ReadError("history paging ended before the stated count")
        for f in page:
            a = f.get("attributes") or {}
            sid, oid = history_id(a), a.get("OBJECTID")
            if not isinstance(oid, int) or oid <= last_oid or oid in oids or sid in ids:
                raise ReadError("history paging repeated an identity or returned rows out of order")
            ids.add(sid)
            oids.add(oid)
            last_oid = oid
            updated = _epoch(edit)
            features.append({**safe_history_feature(f), "fetched_at": at,
                             "layer_updated_at": updated.isoformat() if updated else None})
        if len(features) > count or (len(features) == count and d.get("exceededTransferLimit")):
            raise ReadError("history count changed during paging")
    # Detect a count/edit change during the read, rather than accepting a mixed snapshot.
    after = request(HISTORY_LAYER)
    if (after.get("editingInfo") or {}).get("lastEditDate") != edit \
            or request(query, where="1=1", returnCountOnly="true").get("count") != count:
        raise ReadError("history changed during paging")
    for f in held.get("features") or []:
        if history_id(f["attributes"]) not in ids:
            features.append({**f, "attributes": {k: v for k, v in f["attributes"].items() if k in HISTORY_FIELDS},
                             "missing_since": f.get("missing_since") or at})
    return {"features": features, "current_count": count, "last_edit": edit, "read_at": at,
            "checked_at": at, "parser_version": HISTORY_VERSION}


def _epoch(v) -> datetime | None:
    n = _number(v)
    try:
        return datetime.fromtimestamp(n / 1000, UTC) if n is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def history_when(a: dict, which: str) -> tuple[str | None, str | None]:
    """Decode source time as described in the module docstring."""
    dt = _epoch(a.get(which + "DATE"))
    if dt is None:
        return None, None
    local = dt.astimezone(TZ)
    clock = _epoch(a.get(which + "TIME"))
    if clock is None and (local.hour, local.minute, local.second) == (0, 0, 0):
        return local.date().isoformat(), "day"
    clock = clock.astimezone(TZ) if clock else local
    instant = _local(local.date(), clock.hour, clock.minute)
    if instant is None:
        return local.date().isoformat(), "day"
    if clock.second or clock.microsecond:
        # Existing event precision vocabulary has no seconds; don't claim a more precise clock than we expose.
        instant = instant.replace(second=clock.second, microsecond=clock.microsecond)
    return instant.isoformat(), "minute"


def history_record(f: dict, hist: dict) -> dict:
    a = {k: v for k, v in f["attributes"].items() if k in HISTORY_FIELDS}
    sid = history_id(a)
    started, precision = history_when(a, "START")
    ended, end_precision = history_when(a, "END")
    raw = {"state": "TX", "time_zone": TZ_NAME, "sso_id": sid, "tpdes_permit": None,
           "location": a.get("ADDRESS"), "cause": a.get("CAUSE"), "structure_type": a.get("STRUCTURETYPE"),
           "flow_location": a.get("FLOWLOCATION"), "system": a.get("SYSTEM"),
           "duration_minutes": a.get("DURATION"), "average_flow_gpm": a.get("GPM"),
           "report_kind": "SSO history", "_placement": "named_water_only"}
    if ended and started and (ended[:10] < started[:10] or (
            precision == end_precision == "minute" and datetime.fromisoformat(ended) < datetime.fromisoformat(started))):
        raw["end_note"] = "The source's end precedes its start; we give no end."
        ended = None
    if ended:
        raw["ended_at_precision"] = end_precision
    total = _number(a.get("TOTALVOLLOST"))
    gal = total if total is not None and total > 0 else None
    raw["volume_as_written"] = a.get("TOTALVOLLOST")
    if gal is None:
        raw["volume_note"] = ("The City's history layer gives zero or no total volume; we treat the volume as unknown.")
    else:
        raw["volume_method"] = "Total volume lost as published by the City; we have not recomputed it."
    raw["system_note"] = ("The City's history layer marks this overflow as " + str(a.get("SYSTEM") or "system unspecified")
                          + "; it does not name the system's owner.")
    # No reached-water flag or water name is present. BASIN and WWTP are sewer infrastructure, not receiving waters.
    # Explicit containment is source evidence; proximity ('Within 5 ft') is not evidence that water was reached.
    flow = str(a.get("FLOWLOCATION") or "").lower().replace("’", "'").replace("''", "'")
    if "not cont" not in flow and ("cont'd" in flow or "contained" in flow or "cont’d" in flow):
        raw["reached_water"] = False
        raw["_no_water_reason"] = "The City's history layer describes the flow as contained on site: " + a["FLOWLOCATION"]
    url = HISTORY_LAYER + "/query?" + urlencode({
        "f": "pjson", "where": f"EXCURSIONID={sid}", "outFields": "*", "returnGeometry": "false"})
    updated = _epoch(hist.get("last_edit"))
    raw["history"] = {"attributes": a, "geometry": f.get("geometry"),
                      "fetched_at": f.get("fetched_at") or hist.get("read_at"),
                      "layer_updated_at": f.get("layer_updated_at") or (updated.isoformat() if updated else None)}
    if f.get("missing_since"):
        raw["history"]["missing_since"] = f["missing_since"]
    g = f.get("geometry") or {}
    return event(source_id=SOURCE_ID, source_record_id=sid, event_type="sso", status="ended" if ended else "unknown",
                 outfall_name=a.get("ADDRESS"), started_at=started, ended_at=ended, time_precision=precision,
                 lat=g.get("y"), lon=g.get("x"), coord_source="source" if g else None,
                 coord_precision_m=None, volume_gal=gal,
                 volume_text=f"{gal:g} gallons (City estimate)" if gal else "Volume unknown",
                 estimate_flag="estimated" if gal is not None else "unknown", material="untreated sewage",
                 authority="City of Houston, Houston Public Works, SSO history", source_url=url,
                 fetched_at=raw["history"]["fetched_at"], raw=raw)


def enrich_history(records: list[dict], hist: dict, voided: dict) -> list[dict]:
    """Exact EXCURSIONID only. Monthly reported values prevail; new IDs use the existing source/id scheme."""
    by_id = {str(r["source_record_id"]): r for r in records if str(r["source_record_id"]) not in voided}
    for f in hist.get("features") or []:
        sid = history_id(f["attributes"])
        if sid in voided:
            continue
        h = history_record(f, hist)
        r = by_id.get(sid)
        if r is None or not (r.get("raw") or {}).get("report_month"):
            by_id[sid] = h
            continue
        raw = r["raw"]
        owned = set(raw.get("history_fields") or [])
        monthly = raw.get("monthly_fields") or {}
        for k in owned:
            if k == "cause":
                raw[k] = monthly.get(k)
            else:
                r[k] = monthly.get(k)
        if "volume_gal" in owned:
            r["volume_text"] = monthly.get("volume_text", "Volume unknown")
            r["estimate_flag"] = monthly.get("estimate_flag", "unknown")
            raw["volume_note"] = raw.get("monthly_volume_note")
            raw["volume_as_written"] = raw.get("monthly_volume_as_written")
            raw.pop("volume_method", None)
        if "started_at" in owned:
            r["time_precision"] = monthly.get("time_precision")
        if "ended_at" in owned:
            r["status"] = monthly.get("status", "unknown")
            raw.pop("ended_at_precision", None)
            if raw.get("monthly_end_note"):
                raw["end_note"] = raw["monthly_end_note"]
        raw["history_fields"] = []
        raw["history"] = {**h["raw"]["history"], "url": h["source_url"]}
        for k in ("system", "duration_minutes"):
            raw[k] = h["raw"].get(k)
        raw["report_kind"] = "Monthly SSO Report and SSO history"
        # Each substituted field is explicitly attributed to the layer; PDF publication time remains the PDF's.
        fields = raw.setdefault("history_fields", [])
        for k in ("lat", "lon", "coord_source", "coord_precision_m"):
            if h.get(k) is not None:
                r[k] = h[k]
                if k not in fields:
                    fields.append(k)
        if h.get("lat") is not None:
            raw["place_note"] = "The City's history layer supplies this point; we round it to about 100 meters."
        if not r.get("volume_gal") and h.get("volume_gal") is not None:
            raw["monthly_volume_note"] = raw.pop("volume_note", None)
            raw["monthly_volume_as_written"] = raw.get("volume_as_written")
            for k in ("volume_gal", "volume_text", "estimate_flag"):
                monthly.setdefault(k, r.get(k))
                r[k] = h[k]
                fields.append(k)
            raw["volume_as_written"] = h["raw"]["volume_as_written"]
            raw["volume_method"] = h["raw"].get("volume_method")
        if not r.get("started_at") and h.get("started_at"):
            for k in ("started_at", "time_precision"):
                monthly.setdefault(k, r.get(k))
            r["started_at"], r["time_precision"] = h["started_at"], h["time_precision"]
            fields.append("started_at")
        if not r.get("ended_at") and h.get("ended_at"):
            start, end = r.get("started_at"), h["ended_at"]
            compatible = not start or end[:10] >= start[:10]
            if start and r.get("time_precision") == h["raw"].get("ended_at_precision") == "minute":
                compatible = datetime.fromisoformat(end) >= datetime.fromisoformat(start)
            if compatible:
                for k in ("ended_at", "status"):
                    monthly.setdefault(k, r.get(k))
                r["ended_at"], r["status"] = end, "ended"
                raw["ended_at_precision"] = h["raw"]["ended_at_precision"]
                if raw.get("end_note"):
                    raw["monthly_end_note"] = raw.pop("end_note")
                fields.append("ended_at")
        if not raw.get("cause") and h["raw"].get("cause"):
            monthly.setdefault("cause", raw.get("cause"))
            raw["cause"] = h["raw"]["cause"]
            fields.append("cause")
        if monthly:
            raw["monthly_fields"] = monthly
    return sorted(by_id.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)


# ---------------------------------------------------------------- reading

def http_date(v: str | None) -> str | None:
    """'Fri, 16 Oct 2026 18:43:09 GMT' -> '2026-10-16T18:43:09Z'."""
    try:
        t = parsedate_to_datetime(v) if v else None
    except (TypeError, ValueError):
        return None
    if t is None:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_report(state: dict, month: str, info: dict, content: bytes, at: str, last_modified: str | None,
                pages_of=pdf_pages) -> str:
    """Read one report into the state; returns "new", "revised", "same" or "kept" (a revision that read less fully
    than the copy held, which is kept). ReadError (or pypdf's) when it does not read."""
    sha = hashlib.sha256(content).hexdigest()
    reps = state.setdefault("reports", {})
    prev = reps.get(month)
    if prev and prev.get("sha256") == sha and prev.get("parser_version") == PARSER_VERSION:
        prev["last_seen_at"] = at
        if last_modified and not prev.get("last_modified"):
            prev["last_modified"] = last_modified       # the first date known stays the publication date
        state.setdefault("pending", {}).pop(month, None)  # the copy held answers again (review 2026-11-17 P2-11)
        return "same"
    doc = pages_of(content)
    rep = parse_report(doc["pages"])
    rep.update(url=info["url"], title=info.get("title"), sha256=sha, read_at=at, last_seen_at=at,
               last_modified=last_modified, created=doc.get("created"))
    attempt = {"url": rep["url"], "sha256": sha, "read_at": at, "rows": len(rep["rows"]), "rows_not_read": rep["not_read"],
               "total_stated": rep["total_stated"], "parser_version": PARSER_VERSION}
    if prev and not complete(rep) and (complete(prev) or rep["not_read"] > prev.get("not_read", 0)
                                       or len(rep["rows"]) < len(prev.get("rows") or [])):
        # a revision that reads less completely than the copy held never replaces it, and the month is named until a
        # copy reads whole (review 2026-11-17 P1-5, P1-6)
        prev.setdefault("attempts", []).append(attempt)
        pend = state.setdefault("pending", {})
        pend[month] = {"url": info["url"], "since": (pend.get(month) or {}).get("since") or at, "last_tried": at,
                       "reason": (f"a revised copy did not read completely ({len(rep['rows'])} rows read of "
                                  f"{rep['total_stated']} stated, {rep['not_read']} not read); the earlier copy is kept")}
        return "kept"
    rep["attempts"] = ((prev or {}).get("attempts") or []) + [attempt]
    reps[month] = rep
    state.setdefault("pending", {}).pop(month, None)
    return "revised" if prev else "new"


def complete(rep: dict) -> bool:
    """Every row read and as many as the report states."""
    return not rep.get("not_read") and rep.get("total_stated") is not None and rep["total_stated"] == len(rep.get("rows") or [])


def due(state: dict, links: dict[str, dict], backfill: bool, since: str = BACKFILL_FROM) -> list[str]:
    """The months to ask: never read (on a backfill, or hourly among the NEWEST listed), read before but now listed at
    another address or read by an older parser, pending, and those held to be asked again (the NEWEST hourly, every
    one on a backfill)."""
    listed = sorted(m for m in links if m >= since)
    newest = set(listed[-NEWEST:])
    out = []
    for m in listed:
        rep = (state.get("reports") or {}).get(m)
        if rep is None:
            if backfill or m in newest or m in (state.get("pending") or {}):
                out.append(m)
        elif rep.get("url") != links[m]["url"] or (rep.get("parser_version") or 0) < PARSER_VERSION \
                or m in (state.get("pending") or {}) or backfill or m in newest:
            out.append(m)
    return out


def _get(url: str, headers: dict | None = None):
    return requests.get(url, headers={**HEADERS, **(headers or {})}, timeout=(20, 180))


def run(now: str, state_path: Path = STATE_PATH, out: Path | None = None, get=_get, backfill: bool = False,
        since: str = BACKFILL_FROM, tceq_path: Path | None = TCEQ_EVENTS, pages_of=pdf_pages) -> int:
    state = read_json(state_path, {}) or {}
    previous = read_json(out if out else EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    state["voided"] = {**((previous.get("meta") or {}).get("voided") or {}),
                       **(state.get("voided") or {})}
    if not (state.get("history") or {}).get("features"):
        # A lost state followed by an outage must not erase evidence on a monthly row we can still re-read.
        evidence = [(r.get("raw") or {}).get("history") for r in previous.get("records") or []]
        state["history"] = {"features": [{k: h[k] for k in (
            "attributes", "geometry", "fetched_at", "layer_updated_at", "missing_since") if k in h}
            for h in evidence if h and h.get("attributes")]}
    try:
        r = get(INDEX)
        r.raise_for_status()
        links = report_links(r.text)
        if not links:
            raise ReadError("the index lists no monthly SSO report")
        if not any(m >= since for m in links):          # nothing to carry is no read (review 2026-11-17 P1-8)
            raise ReadError(f"the index lists no monthly SSO report from {since}")
    except (requests.RequestException, ValueError) as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        err = f"index not read ({type(e).__name__}{f', HTTP {code}' if code else ''})"      # never the message
        write_events(SOURCE_ID, [], ok=False, error=err, meta={"index": INDEX}, path=out)
        print(f"{SOURCE_ID}: FAILED {err}", file=sys.stderr)
        return 1
    state["index_read_at"] = now
    state["index_reports"] = links
    pend = state.setdefault("pending", {})
    counts: Counter = Counter()
    for m in due(state, links, backfill, since):
        held = (state.get("reports") or {}).get(m)
        hdrs = {}
        if held and held.get("url") == links[m]["url"] and held.get("parser_version") == PARSER_VERSION \
                and held.get("last_modified") and m not in pend:
            hdrs["If-Modified-Since"] = datetime.fromisoformat(held["last_modified"].replace("Z", "+00:00")) \
                .strftime("%a, %d %b %Y %H:%M:%S GMT")
        try:
            resp = get(links[m]["url"], hdrs) if hdrs else get(links[m]["url"])
            if resp.status_code == 304:
                held["last_seen_at"] = now
                counts["unchanged"] += 1
                continue
            resp.raise_for_status()
            lm = http_date((getattr(resp, "headers", None) or {}).get("Last-Modified"))
            counts[read_report(state, m, links[m], resp.content, now, lm, pages_of=pages_of)] += 1
        except Exception as e:   # noqa: BLE001 - one report's failure never stops the rest
            prev = pend.get(m) or {}
            code = getattr(getattr(e, "response", None), "status_code", None)
            why = (f"the report could not be fetched (HTTP {code})" if code else
                   f"the report could not be read ({type(e).__name__})")       # never the message (a row's text)
            pend[m] = {"url": links[m]["url"], "reason": why, "since": prev.get("since") or now, "last_tried": now}
            counts["pending"] += 1
    history_error = None
    try:
        state["history"] = read_history(state.get("history") or {}, now, get)
    except Exception as e:  # noqa: BLE001 - the last complete history survives a failed page
        history_error = common.error_text(e)
    state["last_read"] = {"at": now, "listed": len(links), **counts}
    recs, voided = build(state)
    state["voided"] = voided
    write_json(state_path, state)
    held = retained(previous, state, recs, voided)
    recs += held
    recs = enrich_history(recs, state.get("history") or {}, voided)
    tdoc = read_json(tceq_path, {}) if tceq_path else {}
    tlinks = link_tceq(recs, (tdoc or {}).get("records") or [])
    reps = state.get("reports") or {}
    listed = sorted(m for m in links if m >= since)
    # a stated total that differs from the rows read, or that could not be read, is named (review 2026-11-17 P1-7)
    mismatch = {m: {"stated": v.get("total_stated"), "read": len(v.get("rows") or [])} for m, v in sorted(reps.items())
                if v.get("total_stated") != len(v.get("rows") or [])}
    meta = {"registry_ids": [SOURCE_ID], "index": INDEX, "credit": AUTHORITY, "legal_basis": DECREE,
            "time_zone": TZ_NAME, "covers_operator": DISCHARGER_ID, "carried_from": since,
            "reports_read": {m: {"title": v.get("title"), "rows": len(v.get("rows") or []),
                                 "total_stated": v.get("total_stated"), "rows_not_read": v.get("not_read", 0),
                                 "reached_waters_of_us": sum(1 for x in v.get("rows") or [] if x["reached"] == "Yes"),
                                 "last_modified": v.get("last_modified"), "read_at": v.get("read_at")}
                             for m, v in sorted(reps.items())},
            "listed_not_read": [m for m in listed if m not in reps and m not in pend],
            "rows_not_read": {m: v["not_read"] for m, v in sorted(reps.items()) if v.get("not_read")},
            "count_mismatch": mismatch, "voided": voided, "pending": dict(sorted(pend.items())),
            "history": {"url": HISTORY_LAYER,
                        "query_template": HISTORY_LAYER + "/query?" + urlencode({
                            "f": "json", "where": "EXCURSIONID={source_record_id}",
                            "outFields": ",".join(HISTORY_FIELDS), "returnGeometry": "true", "outSR": 4326}, safe="{}"),
                        "count": (state.get("history") or {}).get("current_count"),
                        "read_at": (state.get("history") or {}).get("read_at"),
                        "checked_at": (state.get("history") or {}).get("checked_at"), "error": history_error},
            "tceq_links": dict(tlinks), "newest_listed": listed[-1] if listed else None,
            "retained_from_previous_events": sorted({(r.get("raw") or {}).get("report_month") or "" for r in held}),
            "placement_rule": ("We use the City's history-layer point as published and receiving "
                               "waters named by linked TCEQ records. We never locate an overflow by its street or permit.")}
    problems = [f"report {m} not read ({v['reason']})" for m, v in sorted(pend.items())]
    if history_error:
        problems.append("history: " + history_error)
    problems += [f"report {m}: {n} rows not read" for m, n in meta["rows_not_read"].items()]
    problems += [f"report {m}: {v['read']} rows read, {v['stated'] if v['stated'] is not None else 'no total read'} "
                 "stated" for m, v in mismatch.items()]
    if not reps:
        problems.append("no monthly report read")
    # the City's records first, then TCEQ's marks that point to them (review 2026-11-17 P2-12)
    if problems:
        partial = bool(reps or (state.get("history") or {}).get("features"))
        path = write_events(SOURCE_ID, recs, ok=False, partial=partial, meta=meta, path=out,
                            error="; ".join(problems)[:500])
    else:
        path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    if tceq_path and tdoc and tdoc.get("records") is not None:
        tdoc["meta"] = {**(tdoc.get("meta") or {}), "houston_monthly_links": {"at": now, **dict(tlinks)}}
        write_json(tceq_path, tdoc)
    if problems:
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records from {len(reps)} reports; {'; '.join(problems)} -> {path}",
              file=sys.stderr)
        if backfill:
            # the index was read: the backfill saved what it could and names the rest (review 2026-11-17 P1-10)
            print(f"{SOURCE_ID}: backfill saved; not read: {'; '.join(problems)}", file=sys.stderr)
            return 0
        return 1
    print(f"{SOURCE_ID}: {len(recs)} records from {len(reps)} reports (TCEQ links {dict(tlinks)}) -> {path}")
    return 0


def link_only(now: str, events_path: Path = EVENTS_DIR / f"{SOURCE_ID}.json", tceq_path: Path = TCEQ_EVENTS) -> int:
    """The links again after the generic TCEQ reader has run (Makefile INGEST_SNAPSHOTS: ingest.tx_houston_tceq_link),
    so a TCEQ batch read this hour is linked before the status build (review 2026-11-17 P1-9). The City's records are
    read from its events file (whose health is left as its run wrote it); with no such file, or none of its records,
    TCEQ's marks are cleared, so no TCEQ record points to a record the build does not have."""
    tdoc = read_json(tceq_path, {}) or {}
    if tdoc.get("records") is None:
        print(f"{SOURCE_ID}: no TCEQ events file to link")
        return 0
    doc = read_json(events_path, {}) or {}
    recs = [r for r in doc.get("records") or [] if isinstance(r, dict) and isinstance(r.get("raw"), dict)]
    tlinks = link_tceq(recs, tdoc["records"])
    if recs:
        doc["meta"] = {**(doc.get("meta") or {}), "tceq_links": dict(tlinks), "tceq_links_at": now}
        write_json(events_path, doc)
    tdoc["meta"] = {**(tdoc.get("meta") or {}), "houston_monthly_links": {"at": now, **dict(tlinks)}}
    write_json(tceq_path, tdoc)
    print(f"{SOURCE_ID}: TCEQ links {dict(tlinks)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help=f"read every listed report from {BACKFILL_FROM}")
    ap.add_argument("--from", dest="since", default=BACKFILL_FROM, help="the first month to carry (YYYY-MM)")
    ap.add_argument("--file", action="append", help="a saved report PDF, read in place of the live one (needs --month "
                                                    "per file, in order, and --out)")
    ap.add_argument("--month", action="append")
    ap.add_argument("--tceq", help="a TCEQ events file to link against (with --file; the live one is never changed)")
    ap.add_argument("--out")
    ap.add_argument("--link-only", action="store_true", help="only link the City's records to TCEQ's again (after the "
                                                              "generic TCEQ reader)")
    a = ap.parse_args(argv)
    if a.link_only:
        return link_only(now_iso())
    if a.file:
        if not (a.month and len(a.month) == len(a.file) and a.out):
            ap.error("--file needs one --month per file and --out")
        out = Path(a.out)
        state_path = out.with_suffix(".state.json")
        state = read_json(state_path, {}) or {}
        at = now_iso()
        for f, m in zip(a.file, a.month):
            read_report(state, m, {"url": Path(f).name, "title": None}, Path(f).read_bytes(), at, None)
        write_json(state_path, state)
        recs, voided = build(state)
        tdoc = read_json(Path(a.tceq), {}) if a.tceq else {}
        links = link_tceq(recs, (tdoc or {}).get("records") or [])
        if a.tceq:
            write_json(out.with_suffix(".tceq.json"), tdoc)
        write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "tceq_links": dict(links), "voided": voided},
                     path=out)
        print(f"{SOURCE_ID}: {len(recs)} records from {len(a.file)} files (TCEQ links {dict(links)})")
        return 0
    out = Path(a.out) if a.out else None
    return run(now_iso(), out.with_suffix(".state.json") if out else STATE_PATH, out, backfill=a.backfill,
               since=a.since, tceq_path=TCEQ_EVENTS if out is None else None)


if __name__ == "__main__":
    sys.exit(main())
