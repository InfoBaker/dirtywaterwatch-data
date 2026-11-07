"""CT DEEP Performance Dashboard (CSO, SSO and plant-bypass reports) -> data/build/events/ct-deep.json.

Source
------
https://deepct.qscend.mygovcenter.com/cms/cms?id=1, the page DEEP's CSO page calls the
"Bypass / CSO Live Map" and its Sewage Right-to-Know page calls "Current information from
December 1, 2021 forward". Operators file QAlert reports (vendor QScend) under CGS 22a-424a
(electronic report to DEEP within 2 h of becoming aware, updated daily; DEEP posts within 2 h).
The page embeds two Zoho Analytics "open views" on analytics.momixpc.com (Zoho white label,
org 683495554), which are what this module reads:

  1. "Current and Historical View of all CSO's and SSO's" (open view 1914724000008473798, key
     fbd70741...): tab CSO DATA VIEW (report 1914724000016996268) and tab SSO DATA VIEW
     (report 1914724000016996336). One row per report, keyed by Request ID.
  2. "Open CSO and SSO Bypasses by Location" (open view 1914724000008479691, key 098b4e3f...):
     two MAPSCATTER charts of the records whose status is Open, with latitude/longitude at 4
     decimals, status, start date and time, end date, municipality and reach-waterbody yes/no
     (SSO) or receiving waterbody (CSO). The charts carry no Request ID.

Request mechanics (no login, no account)
----------------------------------------
- GET the open-view URL: the response sets the cookie CSRF_TOKEN (plus a session cookie).
- Tables: POST ZDBTableDataAction.ma?ZDBACTION=GENERATETABULARVIEW&OBJID=<report>&
  CONOBJID=<dashboard>&CONFIGID=<config>&privatelink=<key>&... with headers
  X-ZCSRF-TOKEN: ZDB_CSRF_TOKEN=<cookie>, X-Requested-With: XMLHttpRequest,
  ZReports-Current-Org: 683495554, Content-type: text/xml, and the XML body
  <DBSVRequest><dcdet cinfo='false'><zrtlv cr='R TQUARTER,' .../></dcdet>...</DBSVRequest>.
  The server rejects unknown URL parameters (HTTP 400 "Unknown parameter").
  Timeline criteria found to work (2026-11-02): 'R TMONTH,', 'R TQUARTER,', 'R TYEAR,',
  'R MTD,', 'R QTD,', 'R YTD,', 'R TODAY,', 'R TWEEK,', and "last/previous N" keys
  'R L_<n>_<UNIT>S,' (the last n units including the current one) and 'R P_<n>_<UNIT>S,'
  (the n whole units before the current one), UNIT in DAY, MONTH, QUARTER, YEAR; e.g.
  'R P_1_YEARS,' is calendar 2025. Several keys in one cr are ORed; several <zrtlv> elements
  are ANDed. The filter is on the start date (Date Activated / Date Bypass Began). No absolute
  date range syntax was found.
  The response is JSON: reportColNameDetails (column id -> name), grid_param.dataColOrder,
  dataText (rows; each cell [display] or [iso, display]) and navigInfo [start, n, total, ...].
- Maps: POST ZAChartView.ve?CHARTVIEWACTION=CHARTVIEW&OBJID=<chart>&CONOBJID=...&
  FIRSTTIMELOADING=true with a <zadata><dbobj ... type='AnalysisView'><zaav gt='MAPSCATTER' ...>
  body; rows are in chartJSON.seriesdata.chartdata[].data, columns described in
  chartJSON.metadata.columns (dataindex per column name).

The 200-row limit
-----------------
A table response holds at most 200 rows (navigInfo gives the true total) and no paging
parameter was found. Over 200, the server answers the first 200 rows of the window in one of a
few orderings (rows grouped by report type, the group order varying between requests), so
re-requesting the same window adds rows for a few draws and then nothing: some rows of a big
window are never returned. Windows of 200 rows or fewer come back whole. The module therefore
uses the narrowest windows the timeline allows, re-draws a window over 200 rows until its total
is covered or three draws add nothing (budget 4 + 3 x pages, at most 30), and records in
meta.windows each window's total, rows held, draws and whether it was complete. "This quarter"
is far below 200 rows in practice (45 CSO and 18 SSO rows on 2026-11-02), so a poll is one
request per table and window; if it ever exceeds 200 the poll adds "this month".

Data problems handled here
--------------------------
- "Open" is not maintained by operators: SSOs from 2024 still show Open in 2026. Status rules:
  Closed -> ended; Open / In Progress with an end date -> ended; Open with no end that started
  within ONGOING_DAYS (7) of the fetch -> ongoing; older -> unknown (the source status stays in
  raw.Status and a note in raw._dww_note). Carried-over records are re-evaluated every run.
- Missing location: in 2026 the CSO rows of MDC (Hartford), Norwich, Bridgeport West and
  Greater New Haven have CSO Group Name and Receiving Waterbody blank ("null"); only
  Bridgeport East fills them. Those rows get water_slugs [] and water_match "none" and
  raw._dww_note says so. The utility's usual waters are NOT inferred. The only placement
  available for them is the open-events map (coordinates while the record is Open).
- Map coordinates are joined to table rows on (view, municipality, start date, start time)
  because the charts have no Request ID; a key shared by two different points is skipped
  (meta.map). Coordinates are kept on later runs after the record closes and leaves the map.
- Dates and times are separate text fields with typos ("11:45 AM'", "10:30AM", "00:00 AM");
  they are read as America/New_York. Minute precision when the start time parses, else day
  (a day-only start is 00:00, a day-only end 23:59: the conservative ends of the day).
- Volumes are free text in mixed units. Final volume is preferred to the estimate. Ranges,
  bounds ("> 1000 GALLONS", "<500", "Under 5,000"), rates ("80 mgd", "20 gpm") and bare decimals
  with no unit ("0.45") keep the text with volume_gal null. GNH's per-outfall strings
  ("003-0.197 MG 2005 to 2145004-0.023 MG ...") are summed; "No release" is 0; any "No data"
  outfall leaves the total null.
- SSO rows that say Reach Waterbody "No" keep the waterbody text but get no water slug.
- event_type: CSO view "CSO - <utility> ..." -> cso; plant outfall reports ("002-1 -
  Waterbury ...", Norwalk 002-1) -> plant_bypass; SSO view "NPDES Permitted Bypass" or a bypass
  at "Treatment Plant" -> plant_bypass, other SSO view rows -> sso. A 5-day report points to the
  2-hour report of the same utility, start date and start time via parent_event_id.
- No reporter names, emails or phones are in these views; free-text fields are still scrubbed
  of phone numbers and email addresses. Street addresses are kept as DEEP publishes them.
- No submission, publication or update time is exposed: reported_at, published_at and
  source_updated_at stay null, so the 2-hour deadline cannot be checked. No advice text.
- DEEP's caveats: "Data quality, especially volumes, is not checked by DEEP." No terms of use
  were found (the footer links are vendor template residue).

Cadence: poll every 15-30 minutes with the default window ("this quarter", plus "previous
month" so reports filed early in a quarter for events that began in the last days of the
previous one are not missed). Records are merged with the previous file by event_id, so
history from a backfill is kept. --period month|quarter|year changes the window.

--backfill pages both views by Request ID with Zoho's documented ZOHO_CRITERIA URL filter
(&ZOHO_CRITERIA=("CSO BYPASS"."Request ID">=lo and "CSO BYPASS"."Request ID"<hi); the SSO
view's table is "SSO BYPASS"), no timeline filter: one request every 4.5 s, every response saved
raw, a window over 200 rows is halved and asked again, the window widens when rows are sparse,
three empty windows in a row finish a view, and any non-200 answer stops the run without a
retry. Progress is kept in data/build/ct-deep-backfill-state.json so the next run resumes from
the last Request ID (--restart starts over, --max-requests caps a run). The filter was accepted
in a single test on 2026-11-02 (Request ID > 11000 returned 381 CSO rows); the full run has not
been made from this session (the session's permission system blocked it). Rows with no Request
ID cannot be reached this way.

--backfill-timeline is the older backfill through the timeline filter only: it walks every
period the timeline offers (today, this week/month/quarter/year), the previous
month and quarter, month-by-month cuts of this year and last year (TYEAR or P_1_YEARS ANDed
with P_k_MONTHS: only cuts ending at a period boundary are possible), every earlier year and
all rows. It cannot reach every row of 2021-2025 (see the 200-row limit; meta.windows says how
far it got). For 2021-2025 DEEP's annual SRTK spreadsheets (<year>-cso-bypass.xlsx,
<year>-sso-bypass.xlsx) are the complete, reconciled record; this module does not read them.

--from-raw rebuilds the file from every response saved in data/raw/ct-deep/ (no requests).

Run from pipeline/: python -m ingest.ct_deep [--period month|quarter|year] [--backfill [--max-requests N]
[--restart]] [--backfill-timeline] [--from-raw]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, RAW_DIR, write_json, event, now_iso, parse_volume_gal, read_json, save_raw, write_events

# The shared name matcher of the NH/VT ingesters works for any state (state "ct" has no spelling
# table there; CT spellings are applied here first).
from ingest.nh_vt_waters import match_waters as _match_waters, norm, norm_town

SOURCE_ID = "ct-deep"
DASHBOARD_URL = "https://deepct.qscend.mygovcenter.com/cms/cms?id=1"
ZOHO = "https://analytics.momixpc.com"
ORG = "683495554"
TZ = ZoneInfo("America/New_York")
ONGOING_DAYS = 7
PAGE = 200
PAUSE = 0.4

TABLE_VIEW = (f"{ZOHO}/open-view/1914724000008473798/fbd70741d20fe0dd8ee7024ad195cdd2", "fbd70741d20fe0dd8ee7024ad195cdd2")
MAP_VIEW = (f"{ZOHO}/open-view/1914724000008479691/098b4e3f6b2b1adf6b60df5935c7f00a", "098b4e3f6b2b1adf6b60df5935c7f00a")
TABLES = {
    "cso": {"report": "1914724000016996268", "dashboard": "1914724000008473800", "config": "1914724000016996460"},
    "sso": {"report": "1914724000016996336", "dashboard": "1914724000008473805", "config": "1914724000016996432"},
}
MAPS = {
    "cso": {"obj": "1914724000008473922", "dashboard": "1914724000008479693", "config": "1914724000016996757",
            "name": "Open CSO Bypasses by Location"},
    "sso": {"obj": "1914724000008473985", "dashboard": "1914724000008479708", "config": "1914724000017086109",
            "name": "Open SSO Bypasses by Location"},
}

# Report Type utility label (CSO view) or Reporting Utility (SSO view, normalised) -> registry
# (research/ct/dischargers.json ids and permits).
DISCHARGERS = {
    "mdc": ("ct-mdc-hartford", "The Metropolitan District (MDC)", "CT0100251"),
    "mdc hartford wpcf": ("ct-mdc-hartford", "The Metropolitan District (MDC)", "CT0100251"),
    "norwich": ("ct-norwich-npu", "Norwich Public Utilities", "CT0100412"),
    "norwich wpcf": ("ct-norwich-npu", "Norwich Public Utilities", "CT0100412"),
    "bridgeport west side": ("ct-bridgeport-wpca-west", "Bridgeport WPCA West Side", "CT0100056"),
    "bridgeport westside": ("ct-bridgeport-wpca-west", "Bridgeport WPCA West Side", "CT0100056"),
    "bridgeport east side": ("ct-bridgeport-wpca-east", "Bridgeport WPCA East Side", "CT0101010"),
    "bridgeport eastside": ("ct-bridgeport-wpca-east", "Bridgeport WPCA East Side", "CT0101010"),
    "greater new haven": ("ct-gnhwpca", "Greater New Haven WPCA", "CT0100366"),
    "gnhwpca": ("ct-gnhwpca", "Greater New Haven WPCA", "CT0100366"),
    "waterbury": ("ct-waterbury-wpca", "Waterbury WPCF", "CT0100625"),
    "waterbury wpcf": ("ct-waterbury-wpca", "Waterbury WPCF", "CT0100625"),
    "norwalk": ("ct-norwalk-wpca", "Norwalk WPCA", "CT0101249"),
    "norwalk wpcf": ("ct-norwalk-wpca", "Norwalk WPCA", "CT0101249"),
    "naugatuck wpcf": ("ct-naugatuck-wpcf", None, "CT0100641"),
    "derby wpcf": ("ct-derby-wpcf", None, "CT0100161"),
    "middletown wpcf": ("ct-middletown-wpcf", None, "CT0100323"),
    "new london wpcf": ("ct-new-london-wpcf", None, "CT0100382"),
    "shelton wpcf": ("ct-shelton-wpcf", None, "CT0100714"),
    "stamford": ("ct-stamford-wpca", None, "CT0101087"),
    "east windsor wpcf": ("ct-east-windsor-wpca", None, "CT0100196"),
    "stratford wpcf": ("ct-stratford-wpcf", None, "CT0101036"),
    "westport wpcf": ("ct-westport-wpcf", None, "CT0100684"),
    "plainville wpcf": ("ct-plainville-wpcf", None, "CT0100455"),
    "greenwich grass island wpcf": ("ct-greenwich-grass-island", None, "CT0100234"),
    "groton": ("ct-groton-town-wpca", None, "CT0100242"),
}

PLACEHOLDER = re.compile(r"^\s*(null|none|n/?a|na|select\.*|unknown|-|\.)?\s*$", re.I)
PHONE = re.compile(r"(?<!\d)(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
NO_SCRUB = re.compile(r"(volume|quantity|request id|date|time|rainfall)", re.I)


# ---------------------------------------------------------------- small parsers (shared with ct_deep_archive)

def clean(v):
    """Source value or None for Zoho's 'null' and form placeholders ('Select...', 'N/A')."""
    if v is None:
        return None
    s = str(v).strip()
    return None if PLACEHOLDER.match(s) else s


def scrub(rec: dict) -> dict:
    """Remove phone numbers and email addresses from free-text values (names cannot be found
    reliably in free text; the dashboard views have no name columns)."""
    out = {}
    for k, v in rec.items():
        if isinstance(v, str) and not NO_SCRUB.search(str(k)):
            v = EMAIL.sub("[email removed]", PHONE.sub("[phone removed]", v))
        out[k] = v
    return out


def parse_date(s) -> date | None:
    s = clean(s)
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d %b %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s[:11].strip(), fmt).date()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def parse_clock(s) -> tuple[int, int] | None:
    """'02:15 PM', "11:45 AM'", '10:30AM', '00:00 AM', '1430', '7:05 p.m.' -> (hour, minute)."""
    s = clean(s)
    if not s:
        return None
    t = s.upper().replace(".", "").replace("'", "").replace("`", "").strip()
    m = re.fullmatch(r"(\d{1,2})\s*:?\s*(\d{2})\s*(:\d{2})?\s*([AP])?\s*M?", t)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(4)
    if mi > 59:
        return None
    if ap:
        if h > 12:
            return (h, mi) if h < 24 else None   # '13:30 PM': already 24 h
        if ap == "A":
            h = 0 if h == 12 else h
        else:
            h = 12 if h in (0, 12) else h + 12
    if h > 23:
        return None
    return h, mi


def midnight_end(started: str | None, ended: str | None) -> tuple[str | None, str | None]:
    """(ended, note): an end at exactly 00:00 on the start's own calendar day, before the start, is the
    midnight that closes that day (the forms write "00:00 AM" / a date-only stop for it), so it becomes
    00:00 of the next day. Any other end before the start is left as the source gives it."""
    if not started or not ended:
        return ended, None
    s, e = datetime.fromisoformat(started), datetime.fromisoformat(ended)
    if e < s and e.date() == s.date() and (e.hour, e.minute, e.second) == (0, 0, 0):
        nxt = e.date() + timedelta(days=1)
        return datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ).isoformat(), ("end given as 00:00 on the start's own date, before the start: read as the "
                                "midnight that ends that day")
    return ended, None


def local_iso(d: date | None, hm: tuple[int, int] | None, end: bool = False) -> str | None:
    if d is None:
        return None
    if hm is None:
        hm = (23, 59) if end else (0, 0)
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=TZ).isoformat()


def volume(final_text, est_text, final_how=None, est_how=None) -> tuple[int | None, str | None, str]:
    """(gallons, text used, estimate_flag) preferring the final volume."""
    for text, how in ((final_text, final_how), (est_text, est_how)):
        t = clean(text)
        if not t:
            continue
        gal, flag = volume_one(t)
        flag = how_flag(how) or flag
        if gal is not None:
            return gal, t, flag
    # nothing numeric: keep the most informative text
    t = clean(final_text) or clean(est_text)
    how = final_how if clean(final_text) else est_how
    return None, t, (how_flag(how) or ("estimated" if t and re.search(r"\d", t) else "unknown"))


def volume_one(text: str) -> tuple[int | None, str]:
    s = text.strip().lower().replace(",", "")
    if re.fullmatch(r"(no release|zero( gallons?)?|0( gallons?| gal| mg)?)", s):
        return 0, "unknown"
    if re.match(r"^\s*\d{3}\s*-", s):                      # GNH per-outfall string
        if "no data" in s:
            return None, "unknown"
        parts = re.findall(r"(\d*\.?\d+)\s*mg\b(?!d)", s)
        if parts:
            return int(round(sum(float(p) for p in parts) * 1_000_000)), "unknown"
        if "no release" in s:
            return 0, "unknown"
        return None, "unknown"
    if re.match(r"^\s*(<|>|under|over|less than|more than|greater than|up to|minimal|at least|at most|maximum|max)", s) \
            or re.search(r"\b(or less|or more|or fewer|or greater|at most|at least|maximum|minimum)\b|\d\s*\+(?!/)", s):
        return None, "estimated"                             # a bound, not an amount
    m = re.search(r"(\d*\.?\d+)\s*([a-z/]*)\s*(per|/)?\s*([a-z]*)", s)
    if not m:
        return None, "unknown"
    unit, per, after = m.group(2), m.group(3), m.group(4)
    if unit.startswith("mgd") or unit in ("gpm", "gpd", "gph", "cfs") or "/" in unit or (per and after.startswith(("min", "hour", "hr", "day", "sec"))):
        return None, "estimated"                             # a rate, not a volume
    if not unit and "." in m.group(1):
        return None, "unknown"                               # '0.45', '5.32': unit unknown
    gal, flag = parse_volume_gal(s)
    if gal is not None and re.search(r"\+/-|approx|around|about|roughly|estimat", s):
        flag = "estimated"
    mg = re.search(r"(\d+(?:\.\d+)?)\s*(mg|million gallons|million)", s)
    if mg and gal is not None:                               # parse_volume_gal truncates 0.5206 MG to 520599
        gal = int(round(float(mg.group(1)) * 1_000_000))
    return gal, flag


def how_flag(how) -> str | None:
    h = (clean(how) or "").lower()
    if not h:
        return None
    if re.search(r"meter|scada|flow data|measured|metered|gauge|telemetry|level sensor|recorded", h):
        return "measured"
    if re.search(r"visual|estimat|calculat|model|approx|observ|assum|guess|crew|personnel", h):
        return "estimated"
    return None


CT_SPELLING = {
    "ct river": "connecticut river", "conn river": "connecticut river", "connecticutt": "connecticut",
    "pequonnick": "pequonnock", "pequonneck": "pequonnock", "poquonnock": "poquonock",
    "lis": "long island sound", "long island sound": "long island sound",
}
CT_BARE = ["shetucket", "thames", "yantic", "housatonic", "quinnipiac", "naugatuck", "connecticut", "farmington", "norwalk", "saugatuck"]


@lru_cache(maxsize=None)
def _ct_reaches() -> dict[str, set[str]]:
    """CT water records that stand for one reach of a longer water: their slug carries a place
    qualifier (quinnipiac-river-hamden-ct, shetucket-river-norwich-ct ...). slug -> towns."""
    out = {}
    with open(DATA_DIR / "waters-new-england.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["state"] == "CT" and row["slug"] != f"{slug(row['name'])}-ct":
                out[row["slug"]] = {norm_town(t) for t in (row.get("towns") or "").split(";") if t.strip()}
    return out


def match_ct_waters(text, town) -> tuple[list[str], list[str]]:
    """Name match within CT (ingest/nh_vt_waters.match_waters) after CT spellings, plus one more
    guard: a reach record (place-qualified slug) needs the event's town among its towns, so a
    Plainville spill to the Quinnipiac headwaters is not put on the Hamden reach."""
    t = norm(text)
    if not t:
        return [], []
    for bad, good in sorted(CT_SPELLING.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{re.escape(bad)}\b", good, t)
    for bare in CT_BARE:
        t = re.sub(rf"\b{bare}\b(?! river| reservoir| lake| pond| bay| brook| harbor| cove)", f"{bare} river", t)
    slugs, notes = _match_waters(t, "ct", [town] if town else [])
    reaches, keep = _ct_reaches(), []
    for s in slugs:
        if s in reaches and norm_town(town) not in reaches[s]:
            notes.append(f"'{s}' is a reach record for {sorted(reaches[s])}; the event's town {town!r} is not one of them: not used")
        else:
            keep.append(s)
    return keep, notes


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def discharger_for(label: str | None) -> tuple[str | None, str | None, str | None]:
    """(discharger_id, discharger_name, npdes) for a utility label as the source writes it."""
    lab = clean(label)
    if not lab:
        return None, None, None
    key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", lab.lower())).strip()
    for k in (key, f"{key} wpcf"):
        if k in DISCHARGERS:
            did, name, npdes = DISCHARGERS[k]
            return did, name or lab, npdes
    if key.startswith("mdc"):
        return "ct-mdc-hartford", lab, None    # MDC collection system: same authority, no plant permit
    return "ct-" + slug(re.sub(r"\b(wpcf|wpca|wwtp)\b", "", lab, flags=re.I)), lab, None


# ---------------------------------------------------------------- Zoho client

class Zoho:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.tokens: dict[str, str] = {}
        self.requests = 0

    def token(self, view_url: str) -> str:
        if view_url not in self.tokens:
            r = self.s.get(view_url, timeout=60)
            r.raise_for_status()
            save_raw(SOURCE_ID, r.content, f"openview-{view_url.rsplit('/', 2)[-2]}.html")
            tok = self.s.cookies.get("CSRF_TOKEN")
            if not tok:
                raise RuntimeError(f"no CSRF_TOKEN cookie from {view_url}")
            self.tokens[view_url] = tok
        return self.tokens[view_url]

    def post(self, view_url: str, url: str, body: str) -> requests.Response:
        last = None
        for attempt in range(4):
            tok = self.token(view_url)
            h = {"X-ZCSRF-TOKEN": f"ZDB_CSRF_TOKEN={tok}", "X-Requested-With": "XMLHttpRequest",
                 "ZReports-Current-Org": ORG, "Content-type": "text/xml;charset=utf-8", "Referer": view_url}
            try:
                self.requests += 1
                r = self.s.post(url, data=body.encode(), headers=h, timeout=90)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    time.sleep(PAUSE)
                    return r
                last = f"HTTP {r.status_code}: {zoho_error(r.text)}"
                if r.status_code in (401, 403) or "csrf" in r.text.lower():
                    self.tokens.pop(view_url, None)
                    self.s.cookies.clear()
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Zoho request failed: {last}")


def zoho_error(text: str) -> str:
    m = re.search(r"STATUS_MESSAGE_START\s*(.*?)\s*STATUS_MESSAGE_END", text or "", re.S)
    return (m.group(1) if m else (text or "")[:200]).strip()


def table_url(kind: str, key: str) -> str:
    t = TABLES[kind]
    return (f"{ZOHO}/ZDBTableDataAction.ma?ZDBACTION=GENERATETABULARVIEW&OBJID={t['report']}&CONFIGASXML=true"
            f"&OBJTYPE=Report&privatelink={key}&CONOBJID={t['dashboard']}&FROMDASHBOARD=true&FROMNEWDASHBOARD=true"
            f"&DASHEDITMODE=false&CONFIGID={t['config']}&SHOWVMFILTERS=false&APPLYDASHVMFILTERS=true"
            f"&ENABLEALLUSERFILTERS=true&CHANGESLIDERBOUNDS=false&SUBREQUEST=XMLHTTP&_ZVER_=101")


def table_body(criteria: list[str] | None) -> str:
    z = "".join(f"<zrtlv cr='{c}' dcr='x' aot='ABSDATECATEGORICAL' op='PF' st='100' lbl='Timeline Filter' isDashCr='true'/>"
                for c in (criteria or []))
    return f"<DBSVRequest><dcdet cinfo='false'>{z}</dcdet><tvc cinfo='false' jt='1'><tvf></tvf></tvc></DBSVRequest>"


def decode_table(d: dict) -> list[dict]:
    order = (d.get("grid_param") or {}).get("dataColOrder") or list(d.get("reportColNameDetails", {}))
    names = [d["reportColNameDetails"].get(c, c) for c in order]
    rows = []
    for r in d.get("dataText") or []:
        rec = {}
        for n, cell in zip(names, r):
            v = cell[-1] if isinstance(cell, list) and cell else cell
            rec[n] = None if v in ("null", "") else v
        rows.append(rec)
    return rows


def row_key(row: dict) -> str:
    rid = clean(row.get("Request ID"))
    if rid:
        return rid
    return "h" + hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:12]


def row_start_date(kind: str, row: dict) -> date | None:
    return parse_date(row.get("Date Activated") if kind == "cso" else row.get("Date Bypass Began or was Discovered"))


# ---------------------------------------------------------------- windows

def quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def month_shift(d: date, k: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - k, 12)
    return date(y, m + 1, 1)


def window(label: str, today: date) -> tuple[list[str] | None, tuple[date, date] | None]:
    ms, qs = date(today.year, today.month, 1), quarter_start(today)
    if label == "month":
        return ["R TMONTH,"], (ms, today)
    if label == "quarter":
        return ["R TQUARTER,"], (qs, today)
    if label == "year":
        return ["R TYEAR,"], (date(today.year, 1, 1), today)
    if label == "today":
        return ["R TODAY,"], (today, today)
    if label == "week":
        return ["R TWEEK,"], (today - timedelta(days=(today.weekday() + 1) % 7), today)
    m = re.fullmatch(r"(this|last)-year-from-(\d+)", label)   # a year cut to the months after one point
    if m:
        k = int(m.group(2))
        if m.group(1) == "this":
            return ["R TYEAR,", f"R P_{k}_MONTHS,"], (month_shift(today, k), ms - timedelta(days=1))
        return ["R P_1_YEARS,", f"R P_{k}_MONTHS,"], (month_shift(today, k), date(today.year - 1, 12, 31))
    if label == "prev-month":
        return ["R P_1_MONTHS,"], (month_shift(today, 1), ms - timedelta(days=1))
    if label == "prev-quarter":
        return ["R P_1_QUARTERS,"], (month_shift(qs, 3), qs - timedelta(days=1))
    m = re.fullmatch(r"prev-(\d+)-years", label)
    if m:
        k = int(m.group(1))
        return [f"R P_{k}_YEARS,"], (date(today.year - k, 1, 1), date(today.year - 1, 12, 31))
    if label == "all":
        return None, None
    raise ValueError(label)


def collect(z: Zoho, kind: str, label: str, today: date, rows: dict[str, dict], log: list, budget: int = 30,
            same_as: int | None = None) -> dict:
    """Fetch one window. Over PAGE rows, re-draw (the server answers one of a few 200-row cuts at
    random) until the rows held cover the window's total, three draws in a row add nothing, or the
    draw budget is spent (see module docstring). rows: Request ID -> source row, shared across windows."""
    crit, rng = window(label, today)
    url = table_url(kind, TABLE_VIEW[1])
    seen: set[str] = set()
    draws, stall, total = 0, 0, None
    while True:
        r = z.post(TABLE_VIEW[0], url, table_body(crit))
        draws += 1
        save_raw(SOURCE_ID, r.content, f"{kind}-{label}-d{draws:03d}.json")
        d = r.json()
        nav = d.get("navigInfo") or [1, 0, 0]
        total = int(nav[2]) if len(nav) > 2 else len(d.get("dataText") or [])
        new = 0
        for row in decode_table(d):
            k = row_key(row)
            if k not in rows:
                new += 1
            rows[k] = row
            seen.add(k)
        if rng is None:
            have = len(rows)
        else:
            have = len(seen | {k for k, row in rows.items() if (sd := row_start_date(kind, row)) and rng[0] <= sd <= rng[1]})
        pages = max(1, math.ceil(total / PAGE))
        stall = 0 if new else stall + 1
        if draws == 1 and same_as is not None and total == same_as:
            complete = True                                  # same rows as the previous, shorter window
            break
        if total <= PAGE or have >= total:
            complete = True
            break
        if draws >= min(budget, 4 + 3 * pages) or stall >= 3:
            complete = False
            break
    info = {"view": kind, "window": label, "criteria": crit, "total": total, "held": have if total > PAGE else len(seen),
            "draws": draws, "complete": complete}
    log.append(info)
    print(f"  {kind:3s} {label:14s} total {total:5d} held {info['held']:5d} draws {draws:3d} {'complete' if complete else 'INCOMPLETE'}",
          file=sys.stderr)
    return info


# ---------------------------------------------------------------- map charts

def map_body(name: str) -> str:
    return ("<zadata >\n<dbobj   dispname='%s'  desc=''  type='AnalysisView' ><zaav  gt='MAPSCATTER'  sgt='DEF'  title=''"
            "  merge='false'  lp='RIGHT'  lt='Status'  ltm='false'  lf='true'  cinfo='false'  jt='1' >\n"
            "<zavrfv  currentSelValue='{}'  currentChildSelValue='{}' />\n</zaav>\n <zataginfo >\n</zataginfo>\n"
            "</dbobj>\n</zadata>") % name


# ---------------------------------------------------------------- Request ID paging (ZOHO_CRITERIA)

CRITERIA_TABLE = {"cso": "CSO BYPASS", "sso": "SSO BYPASS"}   # the views' base tables
STATE_PATH = BUILD_DIR / "ct-deep-backfill-state.json"
ID_PAUSE = 4.5          # one request every 4-5 seconds
ID_WINDOW = {"cso": 400, "sso": 800}   # first window width in Request IDs (adapts to stay under 200 rows)


def id_criteria(kind: str, lo: int, hi: int) -> str:
    t = CRITERIA_TABLE[kind]
    return f'("{t}"."Request ID">={lo} and "{t}"."Request ID"<{hi})'


def backfill_by_id(z: Zoho, kind: str, rows: dict[str, dict], log: list, state: dict, max_requests: int | None) -> str:
    """Page one view by Request ID ranges with Zoho's documented ZOHO_CRITERIA URL filter, no timeline
    filter. One request every ID_PAUSE seconds, every response saved raw, a window over 200 rows is
    halved and asked again, three empty windows in a row end the view, any non-200 answer stops the
    run (no retry). state[kind] = {"next_id", "window", "done"} lets the next run resume.
    Returns 'done', 'stopped: <why>' or 'paused' (request budget spent)."""
    st = state.setdefault(kind, {"next_id": 0, "window": ID_WINDOW[kind], "done": False, "empty_run": 0})
    if st.get("done"):
        return "done"
    view_url, key = TABLE_VIEW
    n = 0
    while True:
        if max_requests is not None and n >= max_requests:
            return "paused"
        lo, width = int(st["next_id"]), int(st["window"])
        hi = lo + width
        url = table_url(kind, key) + "&ZOHO_CRITERIA=" + requests.utils.quote(id_criteria(kind, lo, hi), safe="")
        tok = z.token(view_url)
        h = {"X-ZCSRF-TOKEN": f"ZDB_CSRF_TOKEN={tok}", "X-Requested-With": "XMLHttpRequest",
             "ZReports-Current-Org": ORG, "Content-type": "text/xml;charset=utf-8", "Referer": view_url}
        time.sleep(ID_PAUSE)
        z.requests += 1
        n += 1
        try:
            r = z.s.post(url, data=table_body(None).encode(), headers=h, timeout=90)
        except requests.RequestException as e:
            return f"stopped: {type(e).__name__} at Request ID {lo}"
        save_raw(SOURCE_ID, r.content, f"{kind}-id{lo:06d}-{hi:06d}.{'json' if r.status_code == 200 else 'err.txt'}")
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/json"):
            return f"stopped: HTTP {r.status_code} at Request ID {lo}-{hi}: {zoho_error(r.text)[:160]}"
        d = r.json()
        nav = d.get("navigInfo") or [1, 0, 0]
        total = int(nav[2]) if len(nav) > 2 else 0
        if total > PAGE:                     # too wide: halve and ask again (nothing kept from this answer)
            st["window"] = max(1, width // 2)
            log.append({"view": kind, "ids": [lo, hi], "total": total, "action": "halve"})
            continue
        got = decode_table(d)
        for row in got:
            rows[row_key(row)] = row
        log.append({"view": kind, "ids": [lo, hi], "total": total, "held": len(got)})
        print(f"  {kind} ids {lo:6d}-{hi:6d} rows {total:3d}", file=sys.stderr)
        st["next_id"] = hi
        st["empty_run"] = 0 if total else st.get("empty_run", 0) + 1
        if total < PAGE // 3:
            st["window"] = min(width * 2, 3200)
        elif total > PAGE * 3 // 4:
            st["window"] = max(1, width * 3 // 4)
        write_json(STATE_PATH, state)
        if st["empty_run"] >= 3:
            st["done"] = True
            st["completed_at"] = now_iso()
            write_json(STATE_PATH, state)
            return "done"


def fetch_map(z: Zoho, kind: str) -> list[dict]:
    m = MAPS[kind]
    url = (f"{ZOHO}/ZAChartView.ve?CHARTVIEWACTION=CHARTVIEW&height=731&width=766&legend=true&OBJID={m['obj']}"
           f"&privatelink={MAP_VIEW[1]}&CONOBJID={m['dashboard']}&FROMDASHBOARD=true&FROMNEWDASHBOARD=true"
           f"&DASHEDITMODE=false&CONFIGID={m['config']}&SHOWVMFILTERS=false&APPLYDASHVMFILTERS=true"
           f"&ENABLEALLUSERFILTERS=true&STANDALONE=true&EDITMODE=false&LP=RIGHT&CHANGESLIDERBOUNDS=false"
           f"&ISAXISDRILL=false&COLLAPSELEGEND=true&RESETSORT=true&FIELDSCHANGED=false&FIRSTTIMELOADING=true"
           f"&SUBREQUEST=XMLHTTP&_ZVER_=101")
    r = z.post(MAP_VIEW[0], url, map_body(m["name"]))
    save_raw(SOURCE_ID, r.content, f"map-open-{kind}.json")
    return decode_map(r.json())


def decode_map(d: dict) -> list[dict]:
    cj = d.get("chartJSON") or {}
    if isinstance(cj, str):
        cj = json.loads(cj)
    idx = {}
    for c in (cj.get("metadata") or {}).get("columns") or []:
        if "dataindex" not in c or c["dataindex"] is None or c["dataindex"] < 0:
            continue
        n, op = c.get("columnname", ""), c.get("operation")
        key = ("count" if op == "COUNT" else "lat" if n == "Latitude" else "lon" if n == "Longitude"
               else "status" if n == "Status" else "start_date" if re.search(r"Date (Activated|Bypass Began)", n)
               else "end_date" if re.search(r"Date (Ceased|Bypass Ended)", n) else "start_time" if n == "Event Start Time"
               else "end_time" if n == "Event End Time" else "municipality" if n in ("Muncipality", "Municipality")
               else "receiving" if n == "Receiving Waterbody" else "reach" if n == "Reach Waterbody" else None)
        if key and key not in idx:
            idx[key] = c["dataindex"]
    pts = []
    for series in (cj.get("seriesdata") or {}).get("chartdata") or []:
        for row in series.get("data") or []:
            p = {k: (row[i] if i < len(row) else None) for k, i in idx.items()}
            for k in ("start_date", "end_date"):
                v = p.get(k)
                p[k] = datetime.fromtimestamp(v / 1000, UTC).date().isoformat() if isinstance(v, (int, float)) else None
            try:
                p["lat"], p["lon"] = float(p.get("lat")), float(p.get("lon"))
            except (TypeError, ValueError):
                p["lat"] = p["lon"] = None
            pts.append(p)
    return pts


def map_key(kind: str, municipality, d, t) -> tuple | None:
    hm = parse_clock(t)
    if not (clean(municipality) and d):
        return None
    return kind, norm(municipality), d if isinstance(d, str) else d.isoformat(), hm


# ---------------------------------------------------------------- normalisation

def report_parts(report_type: str | None) -> tuple[str | None, str | None, str | None]:
    """'CSO - MDC 5 Day Report' -> ('CSO', 'MDC', '5 Day'); '002-1 - Waterbury 5 Day Report' -> ('002-1', 'Waterbury', '5 Day')."""
    rt = clean(report_type)
    if not rt:
        return None, None, None
    m = re.match(r"^\s*(.+?)\s+-\s+(.+?)\s+(\d+\s*(?:Day|Hour|Hr))s?\b", rt, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip(), re.sub(r"\s+", " ", m.group(3)).title()
    m = re.match(r"^\s*(.+?)\s+-\s+(.+)$", rt)
    return (m.group(1).strip(), m.group(2).strip(), None) if m else (None, rt, None)


def status_for(src_status, started_at: str | None, ended_at: str | None, now: datetime) -> tuple[str, str | None]:
    st = (clean(src_status) or "").lower()
    if st == "closed":
        return "ended", None
    if st in ("open", "in progress"):
        if ended_at:
            return "ended", f"source status {src_status!r} but an end date and time are given: treated as ended"
        if started_at and now - datetime.fromisoformat(started_at) <= timedelta(days=ONGOING_DAYS):
            return "ongoing", None
        return "unknown", (f"source status {src_status!r} with no end, started more than {ONGOING_DAYS} days before the fetch: "
                           "DEEP's Open flag is not maintained by operators, so this is not treated as ongoing")
    return "unknown", (f"unrecognised source status {src_status!r}" if st else "no source status")


def normalise(kind: str, row: dict, fetched: str, now: datetime) -> dict:
    notes, errors = [], []
    raw = scrub({k: v for k, v in row.items()})
    raw["_view"] = "CSO DATA VIEW" if kind == "cso" else "SSO DATA VIEW"
    rid = clean(row.get("Request ID"))
    if not rid:
        errors.append("no Request ID")
    rec_id = rid or row_key(row)

    if kind == "cso":
        prefix, utility, report_kind = report_parts(row.get("Report Type"))
        town = clean(row.get("Muncipality"))
        if prefix and prefix.upper().startswith("CSO"):
            etype = "cso"
        elif prefix and re.match(r"^\d{3}", prefix):
            etype = "plant_bypass"
            notes.append(f"treatment-plant outfall {prefix} report (CSO-type plant bypass)")
        else:
            etype = "unknown"
            errors.append(f"unrecognised Report Type {row.get('Report Type')!r}")
        sd, st = parse_date(row.get("Date Activated")), parse_clock(row.get("Event Start Time"))
        ed, et = parse_date(row.get("Date Ceased")), parse_clock(row.get("Event End Time"))
        wtext = clean(row.get("Receiving Waterbody"))
        outfall = clean(row.get("CSO Group Name"))
        vol, vtext, vflag = volume(row.get("Final Volume"), row.get("CSO Estimated Volume"),
                                   row.get("Describe how final volume was determined"),
                                   row.get("How was estimated quantity or rate determined"))
        material = None
        reach = None
        if not wtext and not outfall:
            notes.append("CSO Group Name and Receiving Waterbody are blank in the source (DEEP dashboard, 2026 rows for "
                         "MDC, Norwich, Bridgeport West and GNH): no water assigned; the utility's usual waters are not inferred")
    else:
        utility = clean(row.get("Reporting Utility"))
        report_kind = None
        town = clean(row.get("Municipality"))
        itype = (clean(row.get("Incident Type")) or "").lower()
        loc = clean(row.get("Location of Bypass"))
        if "permitted" in itype or (loc or "").lower() == "treatment plant":
            etype = "plant_bypass"
        elif itype:
            etype = "sso"
        else:
            etype = "unknown"
            errors.append("no Incident Type")
        sd, st = parse_date(row.get("Date Bypass Began or was Discovered")), parse_clock(row.get("Event Start Time"))
        ed, et = parse_date(row.get("Date Bypass Ended")), parse_clock(row.get("Event End Time"))
        wtext = clean(row.get("Waterbody Name"))
        addr = clean(row.get("Address"))
        outfall = ", ".join(x for x in (loc, addr) if x) or None
        vol, vtext, vflag = volume(row.get("Final Quantity"), row.get("Estimated Quantity or Rate of Discharge"),
                                   row.get("How was Final Volume Determined"),
                                   row.get("How was estimated Quantity or Rate Determined"))
        material = clean(row.get("Type of Bypass"))
        reach = clean(row.get("Reach Waterbody"))

    if sd is None:
        errors.append("start date missing or unparseable")
    elif st is None and clean(row.get("Event Start Time")):
        notes.append(f"start time {row.get('Event Start Time')!r} not parsed: day precision")
    started = local_iso(sd, st)
    ended = local_iso(ed, et, end=True)
    if ed and et is None and clean(row.get("Event End Time")):
        notes.append(f"end time {row.get('Event End Time')!r} not parsed: end of day used")
    ended, mnote = midnight_end(started, ended)
    if mnote:
        notes.append(mnote)
    if started and ended and datetime.fromisoformat(ended) < datetime.fromisoformat(started):
        notes.append("end is before start in the source")
    status, snote = status_for(row.get("Status"), started, ended, now)
    if snote:
        notes.append(snote)

    slugs, wnotes = ([], [])
    if wtext:
        if reach and reach.lower() == "no":
            notes.append("source says the discharge did not reach a waterbody (Reach Waterbody: No): no water assigned")
        else:
            slugs, wnotes = match_ct_waters(wtext, town)
            notes += wnotes
            if not slugs:
                notes.append(f"receiving water {wtext!r} has no matching water record")

    did, dname, npdes = discharger_for(utility)
    if notes:
        raw["_dww_note"] = notes
    rec = event(
        source_id=SOURCE_ID, source_record_id=rec_id, event_type=etype, status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=npdes,
        outfall_name=outfall, waterbody_text=wtext, water_slugs=slugs, water_match="name" if slugs else "none",
        started_at=started, ended_at=ended, time_precision=("minute" if st else "day") if sd else None,
        fetched_at=fetched, material=material, volume_gal=vol, volume_text=vtext, estimate_flag=vflag,
        authority=f"{dname or utility or town or 'Permittee not named'} (CT DEEP Performance Dashboard)",
        source_url=DASHBOARD_URL, raw=raw, parse_error="; ".join(errors) or None,
    )
    rec["_key"] = (map_key(kind, town, sd, row.get("Event Start Time")), utility, report_kind, sd, st)
    return rec


def attach_coords(records: list[dict], points: dict[str, list[dict]], meta: dict) -> None:
    by_key = defaultdict(list)
    for kind, pts in points.items():
        for p in pts:
            k = map_key(kind, p.get("municipality"), p.get("start_date"), p.get("start_time"))
            if k and p.get("lat") is not None:
                by_key[k].append(p)
    rec_by_key = defaultdict(list)
    for r in records:
        if r["_key"][0]:
            rec_by_key[r["_key"][0]].append(r)
    matched, ambiguous, unmatched = 0, [], []
    for k, pts in by_key.items():
        coords = {(p["lat"], p["lon"]) for p in pts}
        recs = rec_by_key.get(k, [])
        label = {"view": k[0], "municipality": pts[0].get("municipality"), "start_date": k[2], "start_time": pts[0].get("start_time"),
                 "lat": pts[0]["lat"], "lon": pts[0]["lon"], "count": sum(int(p.get("count") or 1) for p in pts)}
        if not recs:
            unmatched.append(label)
            continue
        if len(coords) > 1:
            ambiguous.append({**label, "points": sorted(coords), "records": [r["source_record_id"] for r in recs]})
            continue
        lat, lon = coords.pop()
        for r in recs:
            r.update(lat=lat, lon=lon, coord_source="source", coord_precision_m=11)
            r["raw"]["_map_point"] = {"lat": lat, "lon": lon, "chart": MAPS[k[0]]["name"]}
            matched += 1
    meta["map"] = {"points": sum(len(v) for v in points.values()), "by_view": {k: len(v) for k, v in points.items()},
                   "records_with_coords_this_run": matched, "ambiguous": ambiguous, "unmatched_points": unmatched,
                   "join": "view + municipality + start date + start time (the charts carry no Request ID)"}


def link_revisions(records: list[dict]) -> int:
    """5-day report -> the 2-hour report of the same utility, start date and start time."""
    groups = defaultdict(dict)
    for r in records:
        _, util, rk, sd, st = r["_key"]
        if util and rk and sd:
            groups[(util, sd, st)].setdefault(rk, []).append(r)
    n = 0
    for g in groups.values():
        first = g.get("2 Hour") or g.get("2 Hr")
        if first and len(first) == 1:
            for rk, rs in g.items():
                if rk.startswith("2 "):
                    continue
                for r in rs:
                    r["parent_event_id"] = first[0]["event_id"]
                    n += 1
    return n


def merge(prev: list[dict], new: list[dict], now: datetime) -> list[dict]:
    """Keep every earlier record; replace by event_id; keep map coordinates after a record leaves the
    open-events map; re-evaluate the status of carried-over records against today's date."""
    out = {r["event_id"]: r for r in prev}
    for r in new:
        old = out.get(r["event_id"])
        if old and r.get("lat") is None and old.get("lat") is not None and old.get("coord_source") == "source":
            for k in ("lat", "lon", "coord_source", "coord_precision_m"):
                r[k] = old[k]
            if "_map_point" in (old.get("raw") or {}):
                r["raw"]["_map_point"] = old["raw"]["_map_point"]
        out[r["event_id"]] = r
    fresh = {r["event_id"] for r in new}
    for eid, r in out.items():
        if eid in fresh:
            continue
        status, snote = status_for((r.get("raw") or {}).get("Status"), r.get("started_at"), r.get("ended_at"), now)
        if status != r["status"]:
            r["status"] = status
            notes = [n for n in r["raw"].get("_dww_note", []) if not n.startswith("source status")]
            r["raw"]["_dww_note"] = notes + ([snote] if snote else [])
    return sorted(out.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)


# ---------------------------------------------------------------- main

def rows_from_raw() -> tuple[dict, dict]:
    """Every saved table response, oldest first (a later copy of a Request ID wins), and the latest
    map response per view. Used by --from-raw to rebuild without new requests."""
    rows = {"cso": {}, "sso": {}}
    points: dict[str, list[dict]] = {}
    for p in sorted((RAW_DIR / SOURCE_ID).glob("*.json")):
        m = re.match(r"^\d{8}T\d{6}Z\.(cso|sso)-.*-d\d+\.json$", p.name)
        mm = re.match(r"^\d{8}T\d{6}Z\.map-open-(cso|sso)\.json$", p.name)
        try:
            if m:
                for row in decode_table(json.loads(p.read_text())):
                    rows[m.group(1)][row_key(row)] = row
            elif mm:
                points[mm.group(1)] = decode_map(json.loads(p.read_text()))
        except (ValueError, KeyError) as e:
            print(f"  skip {p.name}: {e}", file=sys.stderr)
    return rows, points


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", choices=["month", "quarter", "year"], default="quarter")
    ap.add_argument("--backfill", action="store_true",
                    help="page both views by Request ID with ZOHO_CRITERIA (resumes from data/build/ct-deep-backfill-state.json)")
    ap.add_argument("--max-requests", type=int, default=None, help="--backfill: request budget per view for this run")
    ap.add_argument("--restart", action="store_true", help="--backfill: start again from Request ID 0")
    ap.add_argument("--backfill-timeline", action="store_true",
                    help="the older backfill through the timeline filter only (cannot reach every row before 2025)")
    ap.add_argument("--no-map", action="store_true")
    ap.add_argument("--from-raw", action="store_true",
                    help="no requests: rebuild from every table and map response saved in data/raw/ct-deep/")
    args = ap.parse_args(argv)

    global PAUSE
    if args.backfill:
        PAUSE = 1.0     # a few hundred requests: go slowly
    fetched = now_iso()
    now = datetime.now(TZ)
    today = now.date()
    z = Zoho()
    windows_log: list[dict] = []
    rows = {"cso": {}, "sso": {}}
    points: dict[str, list[dict]] = {}
    try:
        if args.from_raw:
            rows, points = rows_from_raw()
        backfill_status = {}
        if args.backfill:
            state = {} if args.restart else (read_json(STATE_PATH, {}) or {})
            for kind in ("cso", "sso"):
                backfill_status[kind] = backfill_by_id(z, kind, rows[kind], windows_log, state, args.max_requests)
                write_json(STATE_PATH, state)
                print(f"  {kind}: {backfill_status[kind]}", file=sys.stderr)
                if backfill_status[kind].startswith("stopped"):
                    break                      # stop the run on a server error; resume next time
        for kind in ("cso", "sso") if not (args.from_raw or args.backfill) else ():
            if args.backfill_timeline:
                # the timeline's own periods, the previous ones, then month-by-month cuts of this year
                # and last year (small windows come back whole), then every earlier year and all rows
                labels = ["today", "week", "month", "prev-month", "quarter", "prev-quarter", "year"]
                labels += [f"this-year-from-{k}" for k in range(1, today.month)]
                labels += [f"last-year-from-{k}" for k in range(today.month, today.month + 12)]
                for lab in labels:
                    collect(z, kind, lab, today, rows[kind], windows_log)
                prev_total = None
                for k in range(1, 8):           # the dashboard starts 2021-12-01: stop when a year adds nothing
                    info = collect(z, kind, f"prev-{k}-years", today, rows[kind], windows_log, same_as=prev_total)
                    if info["total"] == prev_total:
                        break
                    prev_total = info["total"]
                collect(z, kind, "all", today, rows[kind], windows_log)
            else:
                info = collect(z, kind, args.period, today, rows[kind], windows_log)
                if info["total"] > PAGE and args.period != "month":
                    collect(z, kind, "month", today, rows[kind], windows_log)
                collect(z, kind, "prev-month", today, rows[kind], windows_log)
        if not args.no_map and not args.from_raw and not any(v.startswith("stopped") for v in backfill_status.values()):
            for kind in ("cso", "sso"):
                points[kind] = fetch_map(z, kind)
    except Exception as e:  # feed outage: keep the previous records
        print(f"ct_deep: fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        return 1

    records = []
    for kind in ("cso", "sso"):
        for row in rows[kind].values():
            try:
                records.append(normalise(kind, row, fetched, now))
            except Exception as e:  # never drop a record
                rec = event(source_id=SOURCE_ID, source_record_id=row_key(row), fetched_at=fetched, source_url=DASHBOARD_URL,
                            authority="CT DEEP Performance Dashboard", raw=scrub(dict(row)),
                            parse_error=f"{type(e).__name__}: {e}")
                rec["_key"] = (None, None, None, None, None)
                records.append(rec)
    ids = Counter(r["event_id"] for r in records)
    dup = [i for i, n in ids.items() if n > 1]
    for r in records:   # a Request ID in both views (not seen so far): keep both apart
        if r["event_id"] in dup:
            r["source_record_id"] = f"{'cso' if r['raw'].get('_view', '').startswith('CSO') else 'sso'}-{r['source_record_id']}"
            r["event_id"] = f"{SOURCE_ID}:{r['source_record_id']}"
    meta = {"dashboard": DASHBOARD_URL, "tables_view": TABLE_VIEW[0], "maps_view": MAP_VIEW[0],
            "mode": ("from-raw" if args.from_raw else "backfill-by-request-id" if args.backfill
                     else "backfill-timeline" if args.backfill_timeline else args.period),
            "backfill_status": backfill_status, "windows": windows_log, "requests": z.requests,
            "rows_this_run": {k: len(v) for k, v in rows.items()}}
    attach_coords(records, points, meta)
    meta["revision_links"] = link_revisions(records)
    for r in records:
        r.pop("_key", None)

    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    merged = merge(prev, records, now)
    meta["counts"] = {
        "records": len(merged),
        "by_type": dict(Counter(r["event_type"] for r in merged)),
        "by_status": dict(Counter(r["status"] for r in merged)),
        "with_coords": sum(r["lat"] is not None for r in merged),
        "with_slugs": sum(bool(r["water_slugs"]) for r in merged),
        "parse_errors": sum(bool(r["parse_error"]) for r in merged),
    }
    path = write_events(SOURCE_ID, merged, ok=True, meta=meta)
    print(f"ct_deep: {len(records)} rows this run, {len(merged)} records -> {path}", file=sys.stderr)
    print(json.dumps(meta["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
