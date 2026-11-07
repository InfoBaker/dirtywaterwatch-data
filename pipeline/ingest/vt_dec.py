"""VT DEC Sewage Overflows page -> data/build/events/vt-dec.json.

Source: https://anrweb.vt.gov/DEC/WWInventory/SewageOverflows.aspx (Vermont DEC Wastewater
Program). Every untreated discharge from a Vermont wastewater facility is posted here under
10 V.S.A. § 1295: a public alert within 1 hour of discovery (4 h without phone/internet), an
incident report within 12 hours, amended within 3 business days. No API, no RSS, no login.

Access: ASP.NET WebForms. A GET shows the last month; any range is a POST back with the page's
hidden fields (__VIEWSTATE, __EVENTVALIDATION ...) plus ctl00$body$TextBoxDateBegin/End
(MM/DD/YYYY, "Incident Start Date Between") and ctl00$body$ButtonSearch=Search. No paging: a
whole year is one ~250 KB response. Four tables:

  body_GridViewPublicAlerts               operator alerts, not reviewed: facility, town, location,
                                          receiving water, submission time, alert ID
  body_GridViewSewageOverflowsUnOfficial  new incident reports pending DEC review (nForm detail,
                                          separate start/end date and time columns)
  body_GridViewSewageOverflowsOther       reviewed incident reports (SSOs, bypasses, partially
                                          treated effluent, "Other")
  body_GridViewSewageOverflowsAuthorized  reviewed wet-weather CSO reports, one row per outfall

Normalisation (docs/plan.md §3):
- Alerts: status unknown, reported_at = published_at = submission time (DEC: alerts are
  "immediately available for public viewing"); event_type from the location/receiving-water
  text (cso / sso / bypass / unknown). No start, end or volume in the source.
- Incident and CSO reports: started_at/ended_at in America/New_York (the page gives no zone);
  minute precision when both times parse, else day. Status: ended when an end date is given.
  With no end: ongoing if the start is within ONGOING_DAYS of the fetch (the law allows 3
  business days to amend the end), else unknown (an old report with no end is not evidence the
  discharge is still running; marking it ongoing would hold a water red for years).
- Volume: "Estimated Volume (gallons)" via parse_volume_gal; DEC's range buckets (">1,000 to
  10,000 gallons", "Under 100 gallons", ">1,000,000 gallons") keep the text with volume_gal null;
  rates ("gpd", "gpm") and junk (".0425") keep the text only. Every number in this column is
  labelled estimated by the source except "Metered ...".
- Waters: waterbody_text as typed; slugs by name within VT (ingest/nh_vt_waters.py). Rutland's
  East Creek and Springfield's Black River stay unmatched (water_match none).
- Discharger: the facility name; npdes_permit from the ANR active-permit list (research raw) and
  the ECHO outfall registry by facility name; discharger_id from research/nh-vt/dischargers.json
  by permit, else "vt-<facility>". Outfall: outfall_name = the location text; outfall_id = the
  CSO number when exactly one is given (zero-padded to the permit convention, not yet checked
  against the permit tables). No coordinates: the page has none (ingest/outfalls.py joins later).
- parent_event_id: an alert points to its incident report when the facility matches and the
  alert falls between the report's start - 1 day and end + 1 day (outfall-number overlap breaks
  ties, then the nearest start). meta.alert_links lists every report each alert matched.
- Contact persons are dropped (strip_personal) and phone numbers are scrubbed from all text.
- Pending reports move to the reviewed tables under the same submission number once DEC reviews
  them. A pending report missing from the page is kept, marked raw._pending_missing_since, until
  a reviewed report replaces it (same submission number, or same facility and start date) or 90
  days pass. Every other record is kept across runs. A response missing any of the four tables
  is a failed fetch (ok false, previous records kept).

Cadence: poll every 15-30 minutes with the 30-day window (default). --backfill fetches 2016 to
now, one POST per year, reusing research/nh-vt/raw/vt-overflows-YYYY.json (pre-parsed tables
fetched 2026-11-01) for past years; the current year is always fetched live.

Run from pipeline/: python -m ingest.vt_dec [--since DAYS] [--backfill]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests

from common import (EVENTS_DIR, HEADERS, ROOT, event, now_iso, parse_volume_gal, read_json,
                    save_raw, write_events)
from ingest.nh_vt_waters import facility_town, match_waters, norm

SOURCE_ID = "vt-dec"
BASE = "https://anrweb.vt.gov/DEC/WWInventory/"
URL = BASE + "SewageOverflows.aspx"
TZ = ZoneInfo("America/New_York")
ONGOING_DAYS = 7
RESEARCH_RAW = ROOT / "research" / "nh-vt" / "raw"
TABLES = {
    "body_GridViewPublicAlerts": "alert",
    "body_GridViewSewageOverflowsUnOfficial": "pending",
    "body_GridViewSewageOverflowsOther": "reviewed",
    "body_GridViewSewageOverflowsAuthorized": "cso",
}
ADVICE = "Avoid swimming, wading, boating, or fishing after wastewater overflow, releases, or illicit discharges!"
ADVICE_BASIS = ("VT DEC Notice of Untreated or Unpermitted Discharges page (advice); 10 V.S.A. § 1295(e) "
                "and DEC: temporary signs kept posted 48 hours after the discharge has stopped")
PHONE = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]\d{4}\b")


# --------------------------------------------------------------------------- fetch and parse

class _Tables(HTMLParser):
    """Collect <table id=...> rows as lists of cell text; a link is kept as 'text [href]' (the
    same shape as the research raw files)."""

    def __init__(self, ids):
        super().__init__(convert_charrefs=True)
        self.ids, self.tables, self.hidden = set(ids), {}, {}
        self.cur, self.depth, self.row, self.cell, self.href = None, 0, None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("type") == "hidden" and a.get("name"):
            self.hidden[a["name"]] = a.get("value") or ""
        if tag == "table":
            if self.cur:
                self.depth += 1
            elif a.get("id") in self.ids:
                self.cur, self.depth = a["id"], 0
                self.tables[self.cur] = []
            return
        if not self.cur:
            return
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a" and self.cell is not None:
            self.href = a.get("href")
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if not self.cur:
            return
        if tag == "table":
            if self.depth:
                self.depth -= 1
            else:
                self.cur = None
        elif tag == "a" and self.cell is not None and self.href:
            self.cell.append(f" [{self.href}]")
            self.href = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell).replace("\xa0", " ")).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.tables[self.cur].append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def parse_page(html: str) -> tuple[dict[str, list[list[str]]], dict[str, str]]:
    p = _Tables(TABLES)
    p.feed(html)
    return p.tables, p.hidden


def fetch_range(sess: requests.Session, begin: date, end: date, tag: str) -> dict[str, list[list[str]]]:
    r = sess.get(URL, timeout=60)
    r.raise_for_status()
    _, hidden = parse_page(r.text)
    if "__VIEWSTATE" not in hidden:
        raise RuntimeError("no __VIEWSTATE on the overflows page (layout changed?)")
    data = dict(hidden)
    data.update({"ctl00$body$TextBoxDateBegin": begin.strftime("%m/%d/%Y"),
                 "ctl00$body$TextBoxDateEnd": end.strftime("%m/%d/%Y"),
                 "ctl00$body$ButtonSearch": "Search"})
    r = sess.post(URL, data=data, timeout=180)
    r.raise_for_status()
    save_raw(SOURCE_ID, r.content, f"{tag}.html")
    tables, _ = parse_page(r.text)
    check_tables(tables)
    return tables


def check_tables(tables: dict) -> None:
    """All four tables must be present (an empty one still renders its 'No Records Found' row);
    a response missing one is a failed fetch, not an empty table."""
    missing = [t for t in TABLES if t not in tables]
    if missing:
        raise RuntimeError(f"tables missing from the response: {missing}")


# --------------------------------------------------------------------------- helpers

def _link(cell: str) -> tuple[str, str | None]:
    m = re.match(r"^(.*?)\s*\[([^\]]+)\]\s*$", cell or "")
    return (m.group(1).strip(), m.group(2)) if m else ((cell or "").strip(), None)


def _scrub(v):
    if isinstance(v, str):
        return PHONE.sub("[phone removed]", v)
    if isinstance(v, dict):
        return {k: _scrub(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_scrub(x) for x in v]
    return v


def _rows(table: list[list[str]]) -> list[dict[str, str]]:
    if not table:
        return []
    head = [re.sub(r"\s*\[.*$", "", h).strip() or "View" for h in table[0]]
    out = []
    for r in table[1:]:
        if len(r) != len(head) or not any(c.strip() for c in r):
            continue   # "No Records Found In Date Range", empty pager rows
        out.append(dict(zip(head, r)))
    return out


def _date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


_TIME = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)?", re.I)


def _times(s: str) -> list[tuple[int, int]]:
    """'10:55 pm to 01:15 am' -> [(22, 55), (1, 15)]; tolerant of '7:30 - 9:15 am', 'approx 9 pm
    to 12 midnight', 'Start: 9:30 PM End: 6:15 AM'. A token without am/pm borrows the next
    token's; a 1-12 hour with no am/pm anywhere is ambiguous and gives [] (day precision)."""
    s = (s or "").lower()
    if not s.strip() or "unknown" in s:
        return []
    s = s.replace("midnight", "12 am").replace("noon", "12 pm")
    toks = []
    for m in _TIME.finditer(s):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        ap = re.sub(r"[^ap]", "", (m.group(3) or "").lower())
        if h > 23 or mi > 59:
            continue
        toks.append([h, mi, ap])
    for i in range(len(toks) - 2, -1, -1):
        if not toks[i][2] and toks[i + 1][2]:
            toks[i][2] = toks[i + 1][2]
    out = []
    for h, mi, ap in toks[:2]:
        if not ap:
            if 1 <= h <= 12:
                return []
        elif ap == "p" and h < 12:
            h += 12
        elif ap == "a" and h == 12:
            h = 0
        out.append((h, mi))
    return out


def _dt(d: date | None, hm: tuple[int, int] | None) -> datetime | None:
    if d is None:
        return None
    h, m = hm or (0, 0)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _volume(text: str) -> tuple[int | None, str]:
    s = (text or "").strip()
    low = s.lower().replace(",", "")
    if not s or not re.search(r"\d", low):
        return None, "unknown"
    if re.search(r"\bto\b|\d\s*-\s*\d|^[<>]|under|over|less than|more than", low):
        return None, "estimated"            # DEC range bucket or bound: keep the text only
    if re.search(r"gpd|gpm|per day|per minute", low) or re.fullmatch(r"\.\d+", low):
        return None, "unknown"              # a rate or a fraction: not a volume
    gal, _flag = parse_volume_gal(s)
    if gal is None:
        return None, "unknown"
    return gal, "measured" if "meter" in low else "estimated"


_CSO_NUM = re.compile(r"\bcso\s*(?:#|no\.?|number|–|-|—)?\s*(\d{1,3})([a-z])?\b", re.I)


def _outfall_ids(text: str) -> list[str]:
    ids = []
    for m in _CSO_NUM.finditer(text or ""):
        oid = m.group(1).zfill(3) + (m.group(2) or "").upper()
        if oid not in ids:
            ids.append(oid)
    return ids


def classify_alert(loc: str, water: str) -> str:
    t = f"{loc} {water}".lower()
    if re.search(r"\bcso\b|combined sewer", t):
        return "cso"
    if re.search(r"bypass|partial(ly)? treated|partly treated|undisinfected|not fully treated|treatment plant|\bwwtf\b|\bwwtp\b|plant outfall", t):
        return "bypass"
    if re.search(r"\bsso\b|sanitary|manhole|pump ?station|force ?main|sewer (line|main)|main break|backup|overflow|spill", t):
        return "sso"
    return "unknown"


def classify_incident(kind: str, nature: str, loc: str) -> str:
    if kind == "cso":
        return "cso"
    n, l = (nature or "").lower(), (loc or "").lower()
    cso = bool(re.search(r"\bcso\b|combined sewer", l))
    if "untreated" in n:
        if cso:
            return "cso"
        if re.search(r"bypass|headworks|treatment plant|\bwwtf\b|\bwwtp\b|main plant", l):
            return "bypass"
        return "sso"
    if re.search(r"partial|partly|undisinfected|treated and", n):
        return "plant_bypass"
    return "cso" if cso else "unknown"


def _material(kind: str, nature: str) -> str | None:
    if kind == "cso":
        return "untreated sewage and stormwater (authorized wet weather CSO overflow)"
    n = re.sub(r"^discharged\s+", "", (nature or "").strip(), flags=re.I)
    return n or None


# --------------------------------------------------------------------------- registries

def _facility_permits() -> dict[str, str]:
    """Facility name (normalised) -> NPDES permit, from the ANR active-permit list and the ECHO
    outfall registry (both use DEC's facility names)."""
    out: dict[str, str] = {}
    p = RESEARCH_RAW / "vtp-anr-active-npdes-permits-2026-11-01.csv"
    if p.exists():
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        start = next((i for i, l in enumerate(lines) if l.startswith("PermitID,")), None)
        if start is not None:
            for row in csv.DictReader(lines[start:]):
                if row.get("NPDESPermitNumber") and row.get("FacilityName"):
                    out.setdefault(norm(row["FacilityName"]), row["NPDESPermitNumber"].strip())
    reg = read_json(ROOT / "data" / "outfalls-new-england.json", {}) or {}
    for o in reg.get("outfalls", []):
        if o.get("state") == "VT" and o.get("permittee"):
            out.setdefault(norm(o["permittee"]), o["npdes_permit"])
    return out


def _facility_cities() -> dict[str, str]:
    out: dict[str, str] = {}
    p = RESEARCH_RAW / "vtp-anr-active-npdes-permits-2026-11-01.csv"
    if p.exists():
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        start = next((i for i, l in enumerate(lines) if l.startswith("PermitID,")), None)
        if start is not None:
            for row in csv.DictReader(lines[start:]):
                if row.get("FacilityName") and row.get("City"):
                    out.setdefault(norm(row["FacilityName"]), row["City"].strip())
    return out


def _dischargers_by_permit() -> dict[str, str]:
    rows = read_json(ROOT / "research" / "nh-vt" / "dischargers.json", []) or []
    out = {}
    for r in rows:
        if r.get("npdes_permit") and r.get("id", "").startswith("vt-"):
            out.setdefault(r["npdes_permit"], r["id"])
    return out


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


# --------------------------------------------------------------------------- normalise

class Normaliser:
    def __init__(self, fetched_at: str):
        self.fetched_at = fetched_at
        self.fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        self.permits = _facility_permits()
        self.cities = _facility_cities()
        self.dischargers = _dischargers_by_permit()

    def _discharger(self, facility: str) -> tuple[str | None, str | None]:
        permit = self.permits.get(norm(facility))
        if permit is None:   # "St Johnsbury" vs "St. Johnsbury": try without the trailing words
            for k, v in self.permits.items():
                if k.replace(" ", "") == norm(facility).replace(" ", ""):
                    permit = v
                    break
        did = self.dischargers.get(permit) if permit else None
        return permit, did or (f"vt-{_slug(facility)}" if facility else None)

    def _waters(self, text: str, towns: list[str]) -> tuple[list[str], str, list[str]]:
        slugs, notes = match_waters(text, "vt", towns)
        return slugs, ("name" if slugs else "none"), notes

    def _towns(self, facility: str, *extra: str) -> list[str]:
        return [x for x in (*extra, self.cities.get(norm(facility)), facility_town(facility)) if x]

    def alert(self, r: dict[str, str]) -> dict:
        fac, town, loc, water = r["Facility Name"], r["Town"], r["Location Description"], r["Receiving Waters"]
        aid = r["ID"].strip()
        try:
            rep = datetime.strptime(r["Date/Time Submission Entered"].strip(), "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=TZ)
            perr = None
        except ValueError:
            rep, perr = None, f"submission time not parsed: {r['Date/Time Submission Entered']!r}"
        permit, did = self._discharger(fac)
        slugs, wm, notes = self._waters(water, self._towns(fac, town))
        ids = _outfall_ids(loc)
        return event(
            source_id=SOURCE_ID, source_record_id=f"alert:{aid}",
            event_type=classify_alert(loc, water), status="unknown",
            discharger_id=did, discharger_name=fac, npdes_permit=permit,
            outfall_id=ids[0] if len(ids) == 1 else None, outfall_name=_scrub(loc) or None,
            waterbody_text=water or None, water_slugs=slugs, water_match=wm,
            time_precision="minute" if rep else None,
            reported_at=_iso(rep), published_at=_iso(rep), fetched_at=self.fetched_at,
            authority=f"{fac} (operator public alert on the VT DEC Sewage Overflows page; not yet reviewed by DEC)",
            advice_text=ADVICE, advice_window_hours=48, advice_window_basis=ADVICE_BASIS,
            source_url=URL, raw=_scrub({**r, "_table": "Public Alerts", "_match_notes": notes or None}),
            parse_error=perr,
        )

    def incident(self, r: dict[str, str], kind: str) -> dict:
        view, href = _link(r.get("View", ""))
        fac, fhref = _link(r.get("Wastewater Treatment Facility", ""))
        sub = (r.get("Submission Number") or "").strip()
        sd, ed = _date(r.get("Start Date")), _date(r.get("End Date"))
        if kind == "pending":
            st, et = _times(r.get("Start Time")), _times(r.get("End Time"))
            st, et = (st[0] if st else None), (et[0] if et else None)
            have_times = st is not None and (et is not None or ed is None)
        else:
            tt = _times(r.get("Start/End Times"))
            st = tt[0] if tt else None
            et = tt[1] if len(tt) > 1 else None
            have_times = st is not None and (et is not None or ed is None)
        start, end = _dt(sd, st if have_times else None), _dt(ed, et if have_times else None)
        perr = []
        if sd is None:
            perr.append(f"start date not parsed: {r.get('Start Date')!r}")
        if start and end and end < start:
            perr.append("reported end is before the start")
        if end is not None:
            status = "ended"
        elif start is not None and (self.fetched_dt - start) <= timedelta(days=ONGOING_DAYS):
            status = "ongoing"
        else:
            status = "unknown"
        vol_text = (r.get("Estimated Volume (gallons)") or "").strip()
        gal, flag = _volume(vol_text)
        loc, water, nature = r.get("Location", ""), r.get("Waterbody", ""), r.get("Nature of Incident", "")
        etype = classify_incident(kind, nature, loc)
        permit, did = self._discharger(fac)
        slugs, wm, notes = self._waters(water, self._towns(fac, r.get("Municipality", "")))
        ids = _outfall_ids(loc)
        fid = (r.get("ID") or "").strip()
        if kind == "pending":
            rid = f"pending:{sub}"
            url = BASE + href if href else URL
            auth = f"{fac} (incident report on the VT DEC Sewage Overflows page; pending DEC review)"
        else:
            rid = f"incident:{fid}"
            url = BASE + href if href else URL
            auth = f"{fac} (incident report on the VT DEC Sewage Overflows page; reviewed by DEC)"
        raw = {**r, "_table": {"pending": "New Incident Reports (pending review)", "reviewed": "Incident Reports (reviewed)",
                               "cso": "Wet Weather CSO Incident Reports (reviewed)"}[kind],
               "_facility_url": BASE + fhref if fhref else None, "_match_notes": notes or None}
        raw.pop("View", None)
        return event(
            source_id=SOURCE_ID, source_record_id=rid,
            event_type=etype, status=status,
            discharger_id=did, discharger_name=fac or None, npdes_permit=permit,
            outfall_id=ids[0] if len(ids) == 1 else None, outfall_name=_scrub(loc) or None,
            waterbody_text=water or None, water_slugs=slugs, water_match=wm,
            started_at=_iso(start), ended_at=_iso(end),
            time_precision=("minute" if have_times else "day") if start else None,
            fetched_at=self.fetched_at,
            material=_material(kind, nature), volume_gal=gal, volume_text=vol_text or None, estimate_flag=flag,
            authority=auth, advice_text=ADVICE, advice_window_hours=48, advice_window_basis=ADVICE_BASIS,
            source_url=url, raw=_scrub(raw), parse_error="; ".join(perr) or None,
        )

    def tables(self, tables: dict[str, list[list[str]]]) -> list[dict]:
        out = []
        for tid, kind in TABLES.items():
            for r in _rows(tables.get(tid, [])):
                try:
                    out.append(self.alert(r) if kind == "alert" else self.incident(r, kind))
                except Exception as e:   # never drop a record: keep it for the review queue
                    rid = r.get("ID") or r.get("Submission Number") or hashlib.sha1(
                        json.dumps(r, sort_keys=True).encode()).hexdigest()[:12]
                    out.append(event(source_id=SOURCE_ID, source_record_id=f"unparsed:{kind}:{rid}", source_url=URL,
                                     fetched_at=self.fetched_at, raw=_scrub(r), parse_error=f"{type(e).__name__}: {e}"))
        return out


# --------------------------------------------------------------------------- linking and merge

def _key_day(rec: dict) -> date | None:
    t = rec.get("started_at") or rec.get("reported_at")
    return datetime.fromisoformat(t).date() if t else None


def link_alerts(records: list[dict]) -> dict[str, list[str]]:
    """alert.parent_event_id -> its incident report (facility + date); returns all matches."""
    incidents: dict[str, list[dict]] = {}
    for r in records:
        if r["source_record_id"].startswith(("incident:", "pending:")) and r.get("started_at"):
            incidents.setdefault(norm(r["discharger_name"]), []).append(r)
    links = {}
    for a in records:
        if not a["source_record_id"].startswith("alert:"):
            continue
        a["parent_event_id"] = None
        if not a.get("reported_at"):
            continue
        at = datetime.fromisoformat(a["reported_at"])
        aids = set(_outfall_ids(a.get("outfall_name") or ""))
        cands = []
        for i in incidents.get(norm(a["discharger_name"]), []):
            s = datetime.fromisoformat(i["started_at"])
            e = datetime.fromisoformat(i["ended_at"]) if i.get("ended_at") else s
            if s.date() - timedelta(days=1) <= at.date() <= max(e, s).date() + timedelta(days=1):
                overlap = bool(aids & set(_outfall_ids(i.get("outfall_name") or "")))
                cands.append((not overlap, abs((at - s).total_seconds()), i["event_id"]))
        if cands:
            cands.sort()
            a["parent_event_id"] = cands[0][2]
            links[a["event_id"]] = [c[2] for c in cands]
    return links


PENDING_KEEP_DAYS = 90


def _start_day(r: dict) -> str | None:
    return (r.get("started_at") or "")[:10] or None


def merge(prev: list[dict], new: list[dict], fetched_at: str | None = None) -> list[dict]:
    """New records replace old ones by event_id; old records not re-fetched are kept (history).

    A pending report that is no longer on the page is kept until a reviewed report replaces it
    (same submission number, or same facility and start date) or PENDING_KEEP_DAYS pass after it
    dropped out; raw._pending_missing_since records when it was first missed. A pending report
    still on the page is dropped only when a reviewed report carries its submission number."""
    fetched_at = fetched_at or now_iso()
    now = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    new_ids = {r["event_id"] for r in new}
    kept = [r for r in prev if r["event_id"] not in new_ids]
    reviewed = [r for r in kept + new if r["source_record_id"].startswith("incident:")]
    reviewed_subs = {(r.get("raw") or {}).get("Submission Number") for r in reviewed} - {None, ""}
    reviewed_fac_day = {(norm(r.get("discharger_name") or ""), _start_day(r)) for r in reviewed if _start_day(r)}
    out = []
    for r in kept:
        if r["source_record_id"].startswith("pending:"):
            sub = r["source_record_id"].split(":", 1)[1]
            if sub in reviewed_subs or (norm(r.get("discharger_name") or ""), _start_day(r)) in reviewed_fac_day:
                continue                                   # replaced by its reviewed report
            raw = r.setdefault("raw", {})
            raw.setdefault("_pending_missing_since", fetched_at)
            missing = datetime.fromisoformat(raw["_pending_missing_since"].replace("Z", "+00:00"))
            if now - missing > timedelta(days=PENDING_KEEP_DAYS):
                continue                                   # gone from the page for 90 days
        out.append(r)
    for r in new:
        if r["source_record_id"].startswith("pending:"):
            if r["source_record_id"].split(":", 1)[1] in reviewed_subs:
                continue
            (r.get("raw") or {}).pop("_pending_missing_since", None)
        out.append(r)
    out.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or ""), reverse=True)
    return out


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", type=int, default=30, help="days back from today (incident start date)")
    ap.add_argument("--backfill", action="store_true", help="2016 to now, one POST per year")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    norm_ = Normaliser(fetched_at)
    sess = requests.Session()
    sess.headers.update(HEADERS)
    today = datetime.now(TZ).date()
    new: list[dict] = []
    years_meta = {}
    try:
        if args.backfill:
            for y in range(2016, today.year + 1):
                cached = RESEARCH_RAW / f"vt-overflows-{y}.json"
                if y < today.year and cached.exists():
                    tables = json.loads(cached.read_text())
                    check_tables(tables)
                    years_meta[y] = f"research raw {cached.name} (fetched 2026-11-01)"
                else:
                    tables = fetch_range(sess, date(y, 1, 1), min(date(y, 12, 31), today), str(y))
                    years_meta[y] = "fetched"
                recs = norm_.tables(tables)
                years_meta[y] += f", {len(recs)} records"
                new.extend(recs)
        else:
            tables = fetch_range(sess, today - timedelta(days=args.since), today, f"since{args.since}")
            new = norm_.tables(tables)
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: fetch failed: {e}", file=sys.stderr)
        return 1
    # one id per record: later (newer) rows win when years overlap
    dedup = {}
    for r in new:
        dedup[r["event_id"]] = r
    new = list(dedup.values())
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records = merge(prev, new, fetched_at)
    links = link_alerts(records)
    days = sorted(d for d in (_key_day(r) for r in records) if d)
    meta = {
        "url": URL, "window": "backfill 2016-now" if args.backfill else f"last {args.since} days (incident start date)",
        "records_span": [days[0].isoformat(), days[-1].isoformat()] if days else None,
        "years": years_meta or None, "fetched_records": len(new),
        "timezone": "America/New_York (the page gives local times without a zone)",
        "ongoing_rule": f"no end given and start within {ONGOING_DAYS} days of fetch -> ongoing; older -> unknown",
        "alert_links": links,
        "terms": "Page footer: 'Copyright © 2025 State of Vermont. All rights reserved'; no data licence; "
                 "public records under 10 V.S.A. § 1295.",
    }
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"{SOURCE_ID}: {len(new)} fetched, {len(records)} in file -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
