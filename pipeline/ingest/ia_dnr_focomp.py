"""Iowa DNR Field Office Compliance (FOCOMP): the bypass reports filed with DNR's field offices by the state's major
municipal and combined sewer systems -> data/build/events/ia-dnr-focomp-incoming-reports.json.

Source
  https://programs.iowadnr.gov/focomp/ (registry ia-dnr-focomp-incoming-reports): Iowa DNR's public Field Office
  Compliance application. Each facility page (/focomp/Detail/FacilityDetail?facilityID=<State Facility ID>) lists the
  field office's staff actions, among them every "Incoming Report" (a telephone notice or written report from the
  permittee) with its type ("Wet weather bypass", "Non-Wet Weather Bypass", "WW Upset", ...) and its ID; each report's
  page (/focomp/Detail/IncomingReport?stFacID=..&incomingReportID=..) gives the date and time DNR received it, the
  bypass type (Wet weather bypass, Non-Wet Weather Bypass, Anticipated Bypass, Basement Backup) and location type (WWTP
  or Collection System), the receiving stream, the incident's start and end (date and time), the estimated gallons
  (or "unknown"), the incident's address, city, county and point when the field office entered them, whether the
  written report has been received, and the report's details as the field office typed them. 567 IAC 63.6 requires a
  telephone report within 24 hours of an unanticipated bypass and a written report within five days. The reports are
  public records; the application gives no download or feed, so the pages are read one by one.

Which facilities (data/reference/ia-focomp-facilities.json, scripts/ia_focomp_facilities.py)
  The 105 facilities DNR classes Major Municipal, the nine combined sewer systems among them. Minor municipal and
  semi-public facilities (about 930 more) are not read yet. Each run reads at most FACILITY_BUDGET facility pages, the
  ones read longest ago first (a full pass about every five hours at the hourly refresh), and at most REPORT_BUDGET
  report pages: a report of a kept type it has not read, then an open report read more than REREAD_H hours ago (its
  end and gallons are often added later). The first pass reads reports listed from BACKFILL_FROM on.

Records (one per bypass report)
  - Kept: the report types naming a bypass or a sewer overflow (KEEP_TYPES); a report whose bypass type is "Basement
    Backup" is not a discharge to water and makes no record (counted in meta). Upsets, compliance reports and the
    other staff actions are not read.
  - event_type: the location type WWTP -> plant_bypass; Collection System -> sso; neither given -> cso when the details
    name a combined sewer outfall, else bypass (a bypass whose place the report does not say). raw.bypass_type keeps
    DNR's bypass type; an Anticipated Bypass is raw.planned.
  - Times (America/Chicago, the facility's clock; raw.time_zone): started_at the Incident Start date and time (minute
    precision; day precision when no time is given), ended_at the Incident End likewise (raw.ended_at_precision);
    reported_at DNR's Date and Time Received. No end: status unknown (never ongoing: the report does not say it is);
    an end: ended. An incident start after the report's receipt is kept as given (an anticipated bypass).
  - Water: waterbody_text the Receiving Stream as typed (none when blank or marked not applicable); a point only when
    the field office entered the incident's own point (rounded to 0.001 degree); the plant's point is never the
    report's. A report with no stream and no point is kept and listed with its county and operator, placed nowhere.
  - Volume: Estimated Gallons unless "Amount Unknown" is checked (estimate_flag estimated).
  - Operator: npdes_permit by the facility's own point against EPA's plant outfalls of Iowa permits
    (data/outfalls-plants-us.json) within PERMIT_MATCH_M whose permit's city is the facility's (raw.permit_basis); the
    operator (discharger_id, discharger_name) is the operator row holding that permit (data/dischargers.json), named
    from the permittee; with no permit the operator is not established and none is named (DNR's facility name stays in
    raw.facility).
  - Identity: source_record_id the Incoming Report ID; source_url the report's page. A report that leaves the facility
    page keeps its record (raw._unlisted_since). A report re-read later replaces its fields (raw._read_at) only when
    the page carries every control of the form (REQUIRED_INPUTS and the rest) and loses no readable date the earlier
    read had; otherwise the earlier fields stay, the report is retried first next run, and the feed's health is false.
  Privacy: the facility page names DNR staff and the report page the person who reported and the staff member who
  received it: none of those fields is read. Only the report's safe fields are kept; the details text goes through the
  strict scrub (common.scrub_text and every house number, before anything is saved) and the incident address keeps its
  street only. A place described as a private home is found on the text as typed, before the scrub can withhold it,
  and loses its point and street (private_home); a carried place description that was withheld loses them too. data/raw/ keeps the parsed safe fields of each report read, never a page.

Run from pipeline/: python -m ingest.ia_dnr_focomp [--facility-budget N] [--report-budget N]
                    [--facility-file ID=page.html ...] [--report-file ID=page.html ...] [--at ISO]
"""
from __future__ import annotations

import html as htmllib
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest.ia_id_privacy import home_place
from ingest.ia_id_privacy import scrub as strict_scrub

SOURCE_ID = "ia-dnr-focomp-incoming-reports"
BASE = "https://programs.iowadnr.gov/focomp"
FACILITY_URL = BASE + "/Detail/FacilityDetail?facilityID={fac}"
REPORT_URL = BASE + "/Detail/IncomingReport?stFacID={fac}&incomingReportID={rid}"
FACILITIES = DATA_DIR / "reference" / "ia-focomp-facilities.json"
STATE_PATH = BUILD_DIR / "ia-dnr-focomp-state.json"
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
AUTHORITY = "Iowa Department of Natural Resources, field office records (reports filed by the permittee)"
FACILITY_BUDGET = 20
REPORT_BUDGET = 60
FACILITY_INTERVAL_H = 5
REREAD_H = 24
BACKFILL_FROM = "2025-01-01"
PERMIT_MATCH_M = 3000
KEEP_TYPES = re.compile(r"bypass|overflow|\bSSO\b|\bCSO\b", re.I)
# a Receiving Stream that names no water ("Varies", "N/A", "unknown", "ground"): no waterbody_text, kept in raw
NO_WATER = re.compile(r"(?i)n/?a|none|unknown|varies|various|multiple|tbd|-+|\.+|(?:the\s+)?ground|land|dry ditch")
CSO_TEXT = re.compile(r"combined sewer|\bCSO\b", re.I)
# a combined sewer denied ("not a combined sewer", "no CSO outfall", "non-CSO"): not an affirmed type
CSO_DENIED = re.compile(r"(?i)\b(?:no|not|non|never|nor|without)\b[\s-]+(?:\w+\s+){0,3}?(?:a\s+)?(?:combined sewer|CSO)\b")
ENTRY = re.compile(r'<tr\b[^>]*>\s*<td[^>]*>\s*(?P<d1>[\d/]*)\s*</td>\s*<td[^>]*>\s*(?P<d2>[\d/]*)\s*</td>\s*<td[^>]*>'
                   r'(?:(?!</tr>).)*?incomingReportID=(?P<rid>\d+)"[^>]*>\s*Incoming Report - (?P<label>.*?) - (?P=rid)\s*</a>', re.S)


def _clean(s) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).replace("\r", "\n").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", s)).strip()


def _us_date(s: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", (s or "").strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))).date().isoformat()
    except ValueError:
        return None


def parse_facility(page: str) -> dict:
    """{reports: [{rid, label, listed}], lat, lon} from a facility page; ValueError when it is not one. Only the
    report's ID, type and first action date are read (the staff name column is not)."""
    if "Field Office Compliance" not in (page or "") or "Action Date" not in page:
        raise ValueError("not a FOCOMP facility page")
    reports = []
    for m in ENTRY.finditer(page):
        reports.append({"rid": m.group("rid"), "label": _clean(m.group("label")), "listed": _us_date(m.group("d1"))})
    if not reports and re.search(r"incomingReportID=\d+", page):
        # the page links reports the reader cannot read (a changed layout): a failed read, never an empty list
        raise ValueError("the facility page links incoming reports the reader cannot read")
    lat = re.search(r'name="Latitude"[^>]*value="(-?[\d.]+)"', page)
    lon = re.search(r'name="Longitude"[^>]*value="(-?[\d.]+)"', page)
    return {"reports": reports, "lat": float(lat.group(1)) if lat else None, "lon": float(lon.group(1)) if lon else None}


def _input(seg: str, name: str) -> str | None:
    m = re.search(rf'<input\b[^>]*\bname="{name}"[^>]*>', seg)
    if not m:
        return None
    v = re.search(r'\bvalue="([^"]*)"', m.group(0))
    return htmllib.unescape(v.group(1)).strip() if v else ""


def _checked(seg: str, name: str) -> bool:
    m = re.search(rf'<input\b[^>]*\bname="{name}"[^>]*type="checkbox"[^>]*>|<input\b[^>]*type="checkbox"[^>]*\bname="{name}"[^>]*>', seg)
    return bool(m and re.search(r"\bchecked\b", m.group(0)))


def _selected(seg: str, name: str) -> str | None:
    m = re.search(rf'<select\b[^>]*\bname="{name}"[^>]*>(.*?)</select>', seg, re.S)
    if not m:
        return None
    s = re.search(r"<option\b[^>]*\bselected\b[^>]*>([^<]*)", m.group(1))
    v = _clean(s.group(1)) if s else ""
    return None if v in ("", "Select") else v


def _textarea(seg: str, name: str) -> str:
    m = re.search(rf'<textarea\b[^>]*\bname="{name}"[^>]*>(.*?)</textarea>', seg, re.S)
    return _clean(m.group(1)) if m else ""


def scrub(text: str) -> str:
    """The strict free-text scrub (ingest/ia_id_privacy.py): emails, phones, names, every street address's house
    number with its suffix or fraction, coordinates rounded; text that may name a person is withheld whole."""
    return strict_scrub(text or "") or ""


# the form's controls a report page must carry for its fields to replace an earlier read (Astra 2026-11-15 P1-3): a
# page that keeps the labels but renames or drops one of these is a failed read, never a record of nulls
REQUIRED_INPUTS = ("IncomingReportID", "DateReceived", "ReceivedTime", "ReceivingStream", "IncidentStart",
                   "IncidentStartTime", "IncidentEnd", "IncidentEndTime", "EstimatedGallons")
REQUIRED_SELECTS = ("ByPassType", "ByPassLocationType")
REQUIRED_TEXTAREAS = ("ReportDetails",)


def check_form(seg: str) -> None:
    """ValueError naming the controls the report form lacks (renamed or dropped)."""
    missing = [n for n in REQUIRED_INPUTS if _input(seg, n) is None]
    missing += [n for n in REQUIRED_SELECTS if not re.search(rf'<select\b[^>]*\bname="{n}"', seg)]
    missing += [n for n in REQUIRED_TEXTAREAS if not re.search(rf'<textarea\b[^>]*\bname="{n}"', seg)]
    if missing:
        raise ValueError(f"the report form lacks {', '.join(missing)}: a partial read, the earlier fields are kept")


def _clock(t: str | None) -> bool:
    """True for a readable clock value ('09:00', '9:05'); the form's time controls carry 24-hour HH:MM."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (t or "").strip())
    return bool(m and int(m.group(1)) < 24 and int(m.group(2)) < 60)


def check_against(fields: dict, prev: dict | None) -> None:
    """ValueError when a read carries a date or clock value it cannot read, or a re-read would lose a readable date or
    clock the earlier read had (a start, an end or the receipt emptied or made unreadable): a malformed read, never a
    rewrite of what was known and never a midnight made from a damaged clock (lessons 4; Astra verification
    2026-11-15). A clock left blank on a first read is the source giving no time (day precision)."""
    for d, t in (("incident_start", "incident_start_time"), ("incident_end", "incident_end_time"),
                 ("date_received", "time_received")):
        new = fields.get(d)
        if new and not _us_date(new):
            raise ValueError(f"unreadable {d}: a malformed read, the earlier fields are kept")
        if prev and _us_date(prev.get(d) or "") and not _us_date(new or ""):
            raise ValueError(f"{d} emptied where the earlier read had one: the earlier fields are kept")
        clock = (fields.get(t) or "").strip()
        if clock and not _clock(clock):
            raise ValueError(f"unreadable {t}: a malformed read, the earlier fields are kept")
        if prev and _clock(prev.get(t)) and not clock:
            raise ValueError(f"{t} emptied where the earlier read had one: the earlier fields are kept")


def parse_report(page: str) -> dict:
    """The report's safe fields; ValueError when the page is not an incoming report or its form is incomplete. The
    reporter and the staff member who received it are not read. A place the report describes as a private home is
    found before any text is withheld: its point and street are dropped (private_home)."""
    i = (page or "").find('name="IncomingReportID"')
    if i < 0 or "Incident Start" not in page:
        raise ValueError("not a FOCOMP incoming report page")
    seg = page[i:]
    check_form(seg)
    num = lambda v: float(v) if v not in (None, "") and re.fullmatch(r"-?[\d.]+", v) else None  # noqa: E731
    lat, lon = num(_input(seg, "Latitude")), num(_input(seg, "Longitude"))
    gal = num(_input(seg, "EstimatedGallons"))
    # the private-home test runs on the text as typed, before the scrub can withhold it (Astra 2026-11-15 P1-5)
    home = home_place(_textarea(seg, "ReportDetails"), _input(seg, "Location"), _input(seg, "Address"),
                      _textarea(seg, "StepsTaken"))
    if home:
        lat = lon = None
    return {
        "private_home": bool(home),
        "report_id": _input(seg, "IncomingReportID"),
        "closed": _selected(seg, "IsClosed"),
        "date_received": _input(seg, "DateReceived"), "time_received": _input(seg, "ReceivedTime"),
        "bypass_type": _selected(seg, "ByPassType"), "location_type": _selected(seg, "ByPassLocationType"),
        # free text typed by the reporter: the strict scrub before any save (Astra verification 2026-11-15)
        "receiving_stream": scrub(_input(seg, "ReceivingStream") or "") or None,
        "receiving_stream_na": _checked(seg, "ReceivingStreamNA"),
        "incident_start": _input(seg, "IncidentStart"), "incident_start_time": _input(seg, "IncidentStartTime"),
        "incident_end": _input(seg, "IncidentEnd"), "incident_end_time": _input(seg, "IncidentEndTime"),
        "estimated_gallons": gal, "amount_unknown": _checked(seg, "AmountUnknown"),
        "location": None if home else (scrub(_input(seg, "Location") or "") or None),
        "address": None if home else (scrub(_input(seg, "Address") or "") or None),
        "city": _selected(seg, "CityID"), "county": _selected(seg, "CountyID"),
        "lat": round(lat, 3) if lat else None, "lon": round(lon, 3) if lon else None,
        "written_report_received": _input(seg, "WrittenDateReceived") or None,
        "written_report_not_received": _checked(seg, "NotReceived"),
        "details": scrub(_textarea(seg, "ReportDetails")) or None,
        "steps_taken": scrub(_textarea(seg, "StepsTaken")) or None,
    }


def local_time(d: str | None, t: str | None) -> tuple[str | None, str | None]:
    """(ISO with Central offset, precision) of a US date and an optional HH:MM."""
    day = _us_date(d or "")
    if not day:
        return None, None
    y, mo, dd = (int(x) for x in day.split("-"))
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (t or "").strip())
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return datetime(y, mo, dd, int(m.group(1)), int(m.group(2)), tzinfo=TZ).isoformat(), "minute"
    return datetime(y, mo, dd, tzinfo=TZ).isoformat(), "day"


def event_type(rep: dict) -> str:
    loc = (rep.get("location_type") or "").lower()
    if loc == "wwtp":
        return "plant_bypass"
    if loc == "collection system":
        return "sso"
    det = CSO_DENIED.sub(" ", rep.get("details") or "")
    return "cso" if CSO_TEXT.search(det) else "bypass"


def _dist_m(a, b, c, d) -> float:
    k = math.pi / 180
    x = (d - b) * k * math.cos((a + c) / 2 * k)
    return 6371000 * math.hypot(x, (c - a) * k)


def permit_for(fac: dict, lat, lon, plants: list[dict]) -> tuple[str | None, str | None]:
    """(npdes permit, basis) by the facility's own point against EPA's Iowa plant outfalls in its city."""
    if lat is None or lon is None:
        return None, None
    city = (fac.get("city") or "").upper()
    best = None
    for p in plants:
        if (p.get("city") or "").upper() != city or p.get("lat") is None:
            continue
        dm = _dist_m(lat, lon, p["lat"], p["lon"])
        if dm <= PERMIT_MATCH_M and (best is None or dm < best[0]):
            best = (dm, p["npdes_permit"])
    if best is None:
        return None, None
    return best[1], (f"EPA's plant outfall of {best[1]} in {fac.get('city')} lies {round(best[0])} m from DNR's point "
                     "for the facility")


def iowa_plants() -> list[dict]:
    doc = read_json(DATA_DIR / "outfalls-plants-us.json", {}) or {}
    return [r for r in doc.get("outfalls", []) if str(r.get("npdes_permit") or "").startswith("IA")]


_OPERATORS: dict | None = None


def operators() -> dict[str, tuple[str, str]]:
    """{permit: (row id, name)} of Iowa's operator rows (data/dischargers.json): a report is named from the permittee."""
    global _OPERATORS
    if _OPERATORS is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
        _OPERATORS = {p: (r["id"], r["name"]) for r in rows if isinstance(r, dict) and r.get("state") == "IA"
                      for p in r.get("npdes_permits") or [] if p}
    return _OPERATORS


def make_record(rep: dict, fac: dict, listed: dict, permit: tuple, at: str, ops: dict | None = None) -> dict | None:
    if (rep.get("bypass_type") or "").lower() == "basement backup":
        return None
    # the scrub again on every field carried from earlier state (a stricter scrub reaches old reads too)
    home = rep.get("private_home") is True or home_place(rep.get("details"), rep.get("location"),
                                                          rep.get("address"))      # before the text is withheld
    rep = {**rep, **{k: (strict_scrub(rep.get(k)) or None) for k in ("details", "steps_taken", "location", "address")}}
    home = home or home_place(rep.get("details"), rep.get("location"), rep.get("address"))
    if home:
        rep.update(lat=None, lon=None, address=None, location=None)
    elif rep.get("lat") is not None and rep.get("lon") is not None:
        rep.update(lat=round(float(rep["lat"]), 3), lon=round(float(rep["lon"]), 3))
    start, sp = local_time(rep["incident_start"], rep["incident_start_time"])
    end, ep = local_time(rep["incident_end"], rep["incident_end_time"])
    recd, _ = local_time(rep["date_received"], rep["time_received"])
    water = None if rep["receiving_stream_na"] or not rep["receiving_stream"] or \
        rep["receiving_stream"].startswith("[withheld") or \
        NO_WATER.fullmatch(rep["receiving_stream"].strip()) else rep["receiving_stream"].strip()
    gal = None if rep["amount_unknown"] else rep["estimated_gallons"]
    raw = {"facility": fac.get("name"), "st_fac_id": fac.get("st_fac_id"), "program_ids": fac.get("program_ids"),
           "report_type": listed.get("label"), "listed_action_date": listed.get("listed"),
           "bypass_type": rep["bypass_type"], "location_type": rep["location_type"], "closed": rep["closed"],
           "receiving_stream_as_typed": rep["receiving_stream"], "details": rep["details"],
           "steps_taken": rep["steps_taken"], "incident_location": rep["location"], "incident_address": rep["address"],
           "city": rep["city"] or fac.get("city"), "county": f"{rep['county'] or fac.get('county')} County",
           "state": "IA", "written_report_received": rep["written_report_received"],
           "written_report_not_received": rep["written_report_not_received"], "time_zone": TZ_NAME,
           "timezone_note": "Central time: DNR's field office records are Iowa local times", "_read_at": at,
           "date_basis": ("Incident Start and End as the field office entered them; Date and Time Received is when "
                          "DNR received the report")}
    # placed only by the water the report names or its own point, never by the permit's or the plant's receiving
    # water: a report with neither stays unplaced and listed (build/status.py own_place_only; Astra 2026-11-15 P2-4)
    raw["_placement"] = "own_place_only"
    if (rep.get("bypass_type") or "").lower() == "anticipated bypass":
        raw["planned"] = True
    if end:
        raw["ended_at_precision"] = ep
    if permit[0]:
        raw["permit_basis"] = permit[1]
    if home:
        raw["privacy_cut"] = "the report describes a private home: its point and street are not kept"
    op = (operators() if ops is None else ops).get(permit[0]) if permit[0] else None
    if op:
        raw["_discharger_basis"] = f"the operator row holding permit {permit[0]}"
    else:
        raw["_discharger_basis"] = ("no permit matched the facility: the operator is not established (DNR's facility "
                                    "name is in raw.facility)")
    perr = None if start else "no Incident Start the reader can read"
    return event(source_id=SOURCE_ID, source_record_id=rep["report_id"], event_type=event_type(rep),
                 status="ended" if end else "unknown", discharger_name=op[1] if op else None,
                 discharger_id=op[0] if op else None, npdes_permit=permit[0],
                 waterbody_text=water, lat=rep["lat"], lon=rep["lon"],
                 coord_source="source" if rep["lat"] is not None else None,
                 coord_precision_m=150 if rep["lat"] is not None else None,
                 started_at=start, ended_at=end, time_precision=sp, reported_at=recd, published_at=None,
                 source_updated_at=None, fetched_at=at, material="sewage", volume_gal=gal,
                 volume_text=(f"{int(gal):,} gallons (estimated)" if gal is not None else "unknown"),
                 estimate_flag="estimated" if gal is not None else "unknown", authority=AUTHORITY,
                 source_url=REPORT_URL.format(fac=fac.get("st_fac_id"), rid=rep["report_id"]), raw=raw,
                 parse_error=perr)


def _hours_since(a: str | None, b: str) -> float:
    if not a:
        return float("inf")
    pa = datetime.fromisoformat(a.replace("Z", "+00:00"))
    pb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return (pb - pa).total_seconds() / 3600


def due_facilities(facs: list[dict], state: dict, at: str, budget: int) -> list[dict]:
    last = state.get("facilities", {})
    due = [f for f in facs if _hours_since((last.get(f["st_fac_id"]) or {}).get("read_at"), at) >= FACILITY_INTERVAL_H]
    due.sort(key=lambda f: ((last.get(f["st_fac_id"]) or {}).get("read_at") or "", f["st_fac_id"]))
    return due[:budget]


def reports_to_read(state: dict, at: str, budget: int) -> list[tuple[str, str]]:
    """[(facility id, report id)]: unread kept reports first (newest listed first), then open reports due a re-read."""
    reps = state.get("reports", {})
    new, again, retry = [], [], []
    for rid, r in reps.items():
        if not KEEP_TYPES.search(r.get("label") or ""):
            continue
        if r.get("retry") and r.get("read_at"):            # a re-read that failed: first in line (lessons 5)
            retry.append((r["read_at"], r["fac"], rid))
        elif not r.get("read_at"):
            if (r.get("listed") or "9999") >= BACKFILL_FROM:
                new.append((r.get("listed") or "", r["fac"], rid))
        elif r.get("closed") != "Closed" and _hours_since(r["read_at"], at) >= REREAD_H:
            again.append((r["read_at"], r["fac"], rid))
    new.sort(reverse=True)
    again.sort()
    retry.sort()
    return [(f, rid) for _, f, rid in retry + new + again][:budget]


def fold_facility(state: dict, fac: dict, parsed: dict, at: str) -> None:
    st = state.setdefault("facilities", {}).setdefault(fac["st_fac_id"], {})
    st.update(read_at=at, lat=parsed["lat"], lon=parsed["lon"], listed=[r["rid"] for r in parsed["reports"]])
    reps = state.setdefault("reports", {})
    for r in parsed["reports"]:
        cur = reps.setdefault(r["rid"], {"fac": fac["st_fac_id"]})
        cur.update(label=r["label"], listed=r["listed"])
        cur.pop("unlisted_since", None)
    listed = set(st["listed"])
    for rid, r in reps.items():
        if r.get("fac") == fac["st_fac_id"] and rid not in listed and not r.get("unlisted_since"):
            r["unlisted_since"] = at


def scrub_state(state: dict) -> dict:
    """The scrub again on every report's fields kept in the state file (before it is written): free text through the
    strict scrub, and a private home's point and street dropped."""
    for r in (state.get("reports") or {}).values():
        f = r.get("fields")
        if not f:
            continue
        home = f.get("private_home") is True or home_place(f.get("details"), f.get("location"), f.get("address"))
        for k in ("details", "steps_taken", "location", "address", "receiving_stream"):
            f[k] = strict_scrub(f.get(k)) or None
        # a place whose own description was withheld (it may name a person) is treated as a private one: saved
        # before the home test ran on the text as typed, it cannot be told apart (lessons 6)
        placed_withheld = any(str(f.get(k) or "").startswith("[withheld") for k in ("location", "address"))
        if home or placed_withheld or home_place(f.get("details"), f.get("location"), f.get("address")):
            f.update(lat=None, lon=None, address=None, location=None, private_home=True)
    return state


def records(state: dict, facs: dict, plants: list[dict]) -> list[dict]:
    out = []
    for rid, r in sorted(state.get("reports", {}).items()):
        rep = r.get("fields")
        if not rep:
            continue
        fac = facs.get(r["fac"], {"st_fac_id": r["fac"]})
        fst = state.get("facilities", {}).get(r["fac"], {})
        rec = make_record(rep, fac, r, permit_for(fac, fst.get("lat"), fst.get("lon"), plants), r["read_at"])
        if rec is None:
            continue
        if r.get("unlisted_since"):
            rec["raw"]["_unlisted_since"] = r["unlisted_since"]
        out.append(rec)
    return out


PAUSE_S = 0.5      # between two requests: one reader at a time, politely


def get(url: str) -> str:
    import time
    time.sleep(PAUSE_S)
    r = requests.get(url, headers=HEADERS, timeout=(20, 120))
    r.raise_for_status()
    return r.text


def _files(argv, flag) -> dict[str, str]:
    out = {}
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            k, _, v = argv[i + 1].partition("=")
            out[k] = Path(v).read_text()
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    fb = int(argv[argv.index("--facility-budget") + 1]) if "--facility-budget" in argv else FACILITY_BUDGET
    rb = int(argv[argv.index("--report-budget") + 1]) if "--report-budget" in argv else REPORT_BUDGET
    fac_files, rep_files = _files(argv, "--facility-file"), _files(argv, "--report-file")
    offline = bool(fac_files or rep_files)
    fdoc = read_json(FACILITIES, {}) or {}
    facs = {f["st_fac_id"]: f for f in fdoc.get("facilities", [])}
    if not facs:
        write_events(SOURCE_ID, [], ok=False, error=f"no facility list ({FACILITIES.name})")
        return 1
    state = read_json(STATE_PATH, {}) or {}
    errors, read_f, read_r, dropped = [], 0, 0, 0
    todo = [facs[k] for k in fac_files if k in facs] if offline else due_facilities(list(facs.values()), state, at, fb)
    for fac in todo:
        try:
            page = fac_files[fac["st_fac_id"]] if offline else get(FACILITY_URL.format(fac=fac["st_fac_id"]))
            parsed = parse_facility(page)
            before = ((state.get("facilities") or {}).get(fac["st_fac_id"]) or {}).get("listed") or []
            if not parsed["reports"] and before:
                raise ValueError(f"the page lists no report where {len(before)} were listed: a failed read")
            fold_facility(state, fac, parsed, at)
            read_f += 1
        except (requests.RequestException, ValueError) as e:
            errors.append(f"facility {fac['st_fac_id']}: {type(e).__name__}: {str(e)[:120]}")
    pending = ([(state["reports"][k]["fac"], k) for k in rep_files if k in state.get("reports", {})] if offline
               else reports_to_read(state, at, rb))
    saved = []
    for fid, rid in pending:
        try:
            page = rep_files[rid] if offline else get(REPORT_URL.format(fac=fid, rid=rid))
            fields = parse_report(page)
            r = state["reports"][rid]
            check_against(fields, r.get("fields"))
            r.update(fields=fields, read_at=at, closed=fields["closed"])
            r.pop("retry", None)
            saved.append({"report_id": rid, "facility": fid, **fields})
            read_r += 1
        except (requests.RequestException, ValueError) as e:
            # the earlier fields stay; the report is read again first next run, and the feed is not healthy until then
            if rid in state.get("reports", {}):
                state["reports"][rid]["retry"] = True
            errors.append(f"report {rid}: {type(e).__name__}: {str(e)[:120]}")
    for rid, r in sorted((state.get("reports") or {}).items()):
        if r.get("retry") and not any(e.startswith(f"report {rid}:") for e in errors):
            errors.append(f"report {rid}: an earlier read failed and it has not been read again yet")
    if saved and not offline:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "reports": saved}, indent=1).encode(), "json")
    write_json(STATE_PATH, scrub_state(state))
    recs = records(state, facs, iowa_plants())
    dropped = sum(1 for r in state.get("reports", {}).values()
                  if (r.get("fields") or {}).get("bypass_type", "") and r["fields"]["bypass_type"].lower() == "basement backup")
    ok = not (todo and read_f == 0 and errors)
    meta = {"registry_ids": [SOURCE_ID], "url": BASE, "facilities_listed": len(facs), "facilities_read": read_f,
            "reports_read": read_r, "reports_known": len(state.get("reports", {})),
            "basement_backups_not_records": dropped, "errors": errors[:20], "backfill_from": BACKFILL_FROM,
            "cadence": f"{fb} facility pages and {rb} report pages a run, the oldest first"}
    if not ok:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(errors[:5]), meta=meta)
        print(f"{SOURCE_ID}: FAILED {errors[:3]}", file=sys.stderr)
        return 1
    if errors:
        # some pages unread: the readable records are written, the unread ones stay queued for the next run, and the
        # feed's health stays false until they are read
        meta["unread"] = errors[:50]
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error="; ".join(errors[:5]), meta=meta,
                            path=EVENTS_DIR / f"{SOURCE_ID}.json")
        print(f"{SOURCE_ID}: {read_f} facility pages, {read_r} report pages read; {len(errors)} unread; {len(recs)} "
              f"records -> {path}")
        return 0
    path = write_events(SOURCE_ID, recs, meta=meta, path=EVENTS_DIR / f"{SOURCE_ID}.json")
    print(f"{SOURCE_ID}: {read_f} facility pages, {read_r} report pages read; {len(recs)} records -> {path}"
          + (f"; {len(errors)} errors" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
