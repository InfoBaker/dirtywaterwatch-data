"""NH CSO permittees' own notices -> data/build/events/nh-permittees.json.

New Hampshire has no statewide overflow feed and no state notification law; EPA Region 1 NPDES
permits (Part I.H.3.g) require each CSO permittee to post an initial notice within 2 hours and a
supplemental one within 24 hours. Four permittees publish something parseable:

1. Nashua (NH0100170), "History of CSO Occurrences" PDF
   https://www.nashuanh.gov/DocumentCenter/View/11049 (text PDF, ~100 KB, updated monthly; 2013 to
   about one month ago). One table per year: a row per date, Total Flow (MG) and Total Duration
   (min) for CSO 002-009 and 014. Parsed with the pure-Python reader in ingest/nh_pdftext.py
   (pdfplumber/pdftotext are not installed) by column position. One record per date and outfall
   with flow > 0 or a duration: cso, ended, started_at = the date (time_precision day),
   ended_at null (only the duration is given; raw.duration_min keeps it), volume in MG.
2. Manchester (NH0100447), CSO Discharge Notification page (DNN announcements module)
   https://www.manchesternh.gov/Departments/Sewer-and-Stormwater/CSO/CSO-Discharge-Notification
   Only about the 10 latest posts are shown, so items are snapshotted by item id and kept across
   runs. "Activation" posts name no outfall, time or volume: cso, reported_at = Published,
   ongoing until a later "No Activations for 12 Hours" post. That post closes every earlier open
   activation: status ended, ended_at null (no end time is ever stated), raw._ended_before = its
   publish time - 12 h (the latest possible end) with raw._ended_before_basis, time_precision
   "bound"; status.py's no-end rule then applies. The all-clear is itself a record with the same
   bound, linked to the activation it closes (parent_event_id). Waters: the city's two receiving
   waters (Merrimack, Piscataquog), water_match inferred.
3. Portsmouth (NH0100234), CSO page table "Summary of Combined Sewer Overflow Events"
   https://www.portsmouthnh.gov/publicworks/wastewater/combined-sewer-overflows-cso
   Monthly volume (MG) per outfall 10A/10B/013 since 2010, about a month behind; each month links
   a scanned memo PDF (daily detail, not text: not parsed). One record per month and outfall with
   volume > 0: cso, ended, started_at = first of the month, time_precision month.
4. Exeter (NH0100871), Combined Sewer & Sanitary Sewer Overflows page
   https://www.exeternh.gov/publicworks/combined-sewer-sanitary-sewer-overflows
   CSO table (outfall 003, Clemson Pond tide gate to the Squamscott), SSO table (street
   locations) and "Non-disinfected Discharge" paragraphs (WWTP outfall 001 -> plant_bypass).
   Date, total gallons, description; times and durations are taken from the description when
   written as h:mm am/pm. All are after-the-fact notices: status ended.

Outfall coordinates and water slugs come from data/outfalls-new-england.json (EPA ECHO CSO inventory) by
permit + outfall number (water_match outfall_registry, coord_source outfall_layer); waterbody_text
is then ECHO's receiving-water name, since the notices name none. Authority = the permittee.
Advice: NH permits set no public advice window, so advice_text/advice_window_* stay null (RSA
485-A:8 III applies CSO partial-use criteria for 3 days after a discharge, which is a water
quality rule, not public advice).

Each permittee is fetched separately. If one fails (or returns nothing parseable) and others
succeed, the file is written ok=True with that permittee's previous records kept and its health in
meta.partial_failures = {permittee: {discharger_id, npdes_permit, event_id_prefix, water_slugs,
error, failed_at, last_ok_at}}, so status.py can mark that permittee's waters stale; a success
elsewhere never refreshes a failed permittee's clock. meta.permittees holds every permittee's
ok / last_ok_at / last_attempt_at / error / records. All failing -> ok false. Hosts answered the project User-Agent on 2026-11-02; BROWSER_HEADERS
is tried when a host refuses it. Cadence: poll Manchester every 15-30 minutes (live notices);
Nashua, Portsmouth and Exeter daily (monthly or ad hoc updates).

Run from pipeline/: python -m ingest.nh_permittees
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, parse_volume_gal,
                    read_json, save_raw, write_events)
from ingest.nh_pdftext import rows as pdf_rows, text_items
from ingest.nh_vt_waters import match_waters

SOURCE_ID = "nh-permittees"
TZ = ZoneInfo("America/New_York")
URLS = {
    "nashua": "https://www.nashuanh.gov/DocumentCenter/View/11049",
    "manchester": "https://www.manchesternh.gov/Departments/Sewer-and-Stormwater/CSO/CSO-Discharge-Notification",
    "portsmouth": "https://www.portsmouthnh.gov/publicworks/wastewater/combined-sewer-overflows-cso",
    "exeter": "https://www.exeternh.gov/publicworks/combined-sewer-sanitary-sewer-overflows",
}
PERMITTEES = {
    "nashua": {"discharger_id": "nh-nashua-wastewater", "npdes_permit": "NH0100170",
               "discharger_name": "City of Nashua Wastewater Department",
               "authority": "City of Nashua Wastewater Department (History of CSO Occurrences PDF)"},
    "manchester": {"discharger_id": "nh-manchester-epd", "npdes_permit": "NH0100447",
                   "discharger_name": "City of Manchester DPW Environmental Protection Division",
                   "authority": "City of Manchester EPD (CSO Discharge Notification page)"},
    "portsmouth": {"discharger_id": "nh-portsmouth-peirce-island", "npdes_permit": "NH0100234",
                   "discharger_name": "City of Portsmouth DPW Wastewater Division",
                   "authority": "City of Portsmouth DPW (CSO page, monthly summary table)"},
    "exeter": {"discharger_id": "nh-exeter-wwtp", "npdes_permit": "NH0100871",
               "discharger_name": "Town of Exeter DPW",
               "authority": "Town of Exeter DPW (Combined Sewer & Sanitary Sewer Overflows page)"},
}
CSO_MATERIAL = "combined sewage and stormwater (CSO)"
ADVICE_NOTE = ("NH permits set no public advice window: advice_text and advice_window_* are null. "
               "RSA 485-A:8 III applies CSO partial-use criteria up to 3 days after a discharge (water "
               "quality rule, not public advice).")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}


# --------------------------------------------------------------------------- shared

def _get(sess: requests.Session, url: str, used_browser: list) -> requests.Response:
    r = sess.get(url, timeout=90)
    if r.status_code in (403, 406, 429) or (r.ok and len(r.content) < 500):
        r = sess.get(url, timeout=90, headers=BROWSER_HEADERS)
        used_browser.append(url)
    r.raise_for_status()
    return r


_REG = None


def outfall(permit: str, number: str) -> dict | None:
    global _REG
    if _REG is None:
        _REG = {}
        for o in (read_json(DATA_DIR / "outfalls-new-england.json", {}) or {}).get("outfalls", []):
            _REG.setdefault((o["npdes_permit"], str(o["outfall"]).upper()), o)
    return _REG.get((permit, str(number).upper()))


def _placed(permit: str, number: str | None) -> dict:
    """Fields from the outfall registry, or nothing."""
    o = outfall(permit, number) if number else None
    if not o:
        return {}
    f = {"outfall_id": o["outfall"], "waterbody_text": o.get("receiving_water_echo")}
    if o.get("outfall_name"):
        f["outfall_name"] = o["outfall_name"]
    if o.get("lat") is not None:
        f.update(lat=o["lat"], lon=o["lon"], coord_source="outfall_layer")
    if o.get("water_slug"):
        f.update(water_slugs=[o["water_slug"]], water_match="outfall_registry")
    return f


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


class _Blocks(HTMLParser):
    """Flatten an HTML page to blocks in order: ('h', text), ('p', text), ('table', rows); a link
    in a cell is kept as cell text plus '[href]'."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf, self.kind = [], None, None
        self.table, self.row, self.cell, self.depth, self.href = None, None, None, 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.table is not None:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th"):
                self.cell = []
            elif tag == "a":
                self.href = a.get("href")
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "p", "li"):
            self.buf, self.kind = [], ("h" if tag.startswith("h") else "p")
        elif tag == "br" and self.buf is not None:
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.blocks.append(("table", self.table))
                self.table = None
        elif self.table is not None:
            if tag == "a" and self.cell is not None and self.href:
                self.cell.append(f" [{self.href}]")
                self.href = None
            elif tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(_clean("".join(self.cell)))
                self.cell = None
            elif tag == "tr" and self.row is not None:
                if any(self.row):
                    self.table.append(self.row)
                self.row = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "p", "li") and self.buf is not None:
            t = _clean("".join(self.buf))
            if t:
                self.blocks.append((self.kind, t))
            self.buf = None

    def handle_data(self, data):
        if self.table is not None and self.cell is not None:
            self.cell.append(data)
        elif self.buf is not None:
            self.buf.append(data)


def blocks(html: str) -> list:
    p = _Blocks()
    p.feed(html)
    return p.blocks


def _ev(key: str, rid: str, **f) -> dict:
    p = PERMITTEES[key]
    base = dict(source_id=SOURCE_ID, source_record_id=f"{key}:{rid}", discharger_id=p["discharger_id"],
                discharger_name=p["discharger_name"], npdes_permit=p["npdes_permit"], authority=p["authority"],
                source_url=URLS[key])
    base.update(f)
    return event(**base)


def _day(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat()


# --------------------------------------------------------------------------- Nashua

def nashua(pdf: bytes, fetched_at: str) -> list[dict]:
    items = text_items(pdf)
    if not items:
        raise RuntimeError("no text extracted from the Nashua PDF (scanned or changed format)")
    out, cols, year, cso_ids, names, want_names = [], None, None, None, {}, False
    for row in pdf_rows(items):
        texts = [i["text"].strip() for i in row]
        if any(t.startswith("CSO ") for t in texts) and texts[0] == "Date":
            cso_ids = [re.sub(r"\D", "", t).zfill(3) for t in texts if t.startswith("CSO ")]
            want_names = True
            continue
        if want_names:
            want_names = False
            if cso_ids and len(texts) == len(cso_ids) and not re.match(r"\d", texts[0]):
                names = dict(zip(cso_ids, texts))
                continue
        if "Total Flow" in texts:
            starts = [i["x"] for i in row if i["text"].strip() in ("Total Flow", "Total Duration")]
            labels = [i["text"].strip() for i in row if i["text"].strip() in ("Total Flow", "Total Duration")]
            if cso_ids and len(labels) == 2 * len(cso_ids):
                cols = [(x, cso_ids[k // 2], "flow" if lab == "Total Flow" else "dur")
                        for k, (x, lab) in enumerate(zip(starts, labels))]
            y = [t for t in texts if re.fullmatch(r"\d{4}", t)]
            year = y[0] if y else year
            continue
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texts[0]) if texts else None
        if not m or not cols:
            continue
        d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        cells: dict[str, dict] = {}
        for it in row[1:]:
            x = it["x"]
            col = None
            for cx, oid, kind in cols:
                if cx <= x + 6:
                    col = (oid, kind)
            if col:
                cells.setdefault(col[0], {})[col[1]] = it["text"].strip()
        for oid, v in sorted(cells.items()):
            flow, dur = v.get("flow"), v.get("dur")
            perr = None
            gal = None
            if flow:
                if re.fullmatch(r"\d*\.\d+|\d+", flow):
                    gal = round(float(flow) * 1_000_000)
                else:
                    perr = f"flow not a number: {flow!r}"
            if gal == 0 and not dur:
                continue
            placed = _placed("NH0100170", oid)
            reg_name = placed.pop("outfall_name", None)
            out.append(_ev("nashua", f"{d.isoformat()}:{oid}",
                           event_type="cso", status="ended",
                           outfall_id=oid, outfall_name=names.get(oid) or reg_name,
                           **{k: v2 for k, v2 in placed.items() if k != "outfall_id"},
                           started_at=_day(d), time_precision="day", fetched_at=fetched_at,
                           material=CSO_MATERIAL, volume_gal=gal, volume_text=f"{flow} MG" if flow else None,
                           estimate_flag="unknown",
                           raw={"date": texts[0], "outfall": f"CSO {oid}", "total_flow_mg": flow,
                                "duration_min": int(dur) if dur and dur.isdigit() else dur, "table_year": year},
                           parse_error=perr))
    return out


# --------------------------------------------------------------------------- Manchester

def manchester(html: str, fetched_at: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<div id="(Item\d+)" class="Announcement">(.*?)(?=<div id="Item\d+" class="Announcement">|</div>\s*</div>\s*<div class="DNN|$)', html, re.S):
        iid, body = m.group(1), m.group(2)
        title = _clean(re.sub(r"<[^>]+>", " ", (re.search(r"<h4>(.*?)</h4>", body, re.S) or [None, ""])[1]))
        pub = re.search(r"Published:\s*(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)", body)
        text = _clean(re.sub(r"<[^>]+>", " ", re.sub(r"<div class=\"Header.*?</div>", " ", body, flags=re.S)))
        published = None
        if pub:
            published = datetime.strptime(f"{pub.group(1)} {pub.group(2)}", "%m/%d/%Y %I:%M %p").replace(tzinfo=TZ)
        low = title.lower()
        kind = "all_clear" if "no activation" in low else ("activation" if "activation" in low else "other")
        out.append(_ev("manchester", iid,
                       event_type="cso" if kind != "other" else "unknown",
                       status="ongoing" if kind == "activation" else ("ended" if kind == "all_clear" else "unknown"),
                       waterbody_text=None, water_slugs=["merrimack-river-nh", "piscataquog-river-nh"],
                       water_match="inferred",
                       reported_at=published.isoformat() if published else None,
                       published_at=published.isoformat() if published else None,
                       time_precision="minute" if published else None, fetched_at=fetched_at,
                       material=CSO_MATERIAL if kind != "other" else None,
                       source_url=f"{URLS['manchester']}#{iid}",
                       raw={"item_id": iid, "title": title, "published": pub.group(0) if pub else None,
                            "body": text[:1000], "kind": kind},
                       parse_error=None if published else "Published time not found"))
    return out


def _require(recs: list[dict], what: str) -> list[dict]:
    if not recs:
        raise RuntimeError(f"no {what} parsed (page layout changed?)")
    return recs


def pair_manchester(records: list[dict]) -> None:
    """An all-clear ("No Activations for 12 Hours") closes every earlier open activation. The
    notice gives only an upper bound on the end (no activation in the 12 h before it was
    published), so ended_at stays null: status ended, raw._ended_before = publish time - 12 h,
    time_precision "bound". The all-clear record links to the activation it closes."""
    ms = [r for r in records if r["source_record_id"].startswith("manchester:") and r.get("reported_at")]
    ms.sort(key=lambda r: (r["reported_at"], int(re.sub(r"\D", "", r["raw"]["item_id"]) or 0)))
    open_acts: list[dict] = []
    for r in ms:
        kind = r["raw"].get("kind")
        r["ended_at"] = None
        r["raw"].pop("ended_at_basis", None)               # older runs wrote an exact end here
        if kind == "activation":
            r.update(status="ongoing", time_precision="minute")
            r["raw"].pop("_ended_before", None)
            r["raw"].pop("_ended_before_basis", None)
            open_acts.append(r)
        elif kind == "all_clear":
            bound = (datetime.fromisoformat(r["reported_at"]) - timedelta(hours=12)).isoformat()
            basis = (f"'No Activations for 12 Hours' notice {r['raw']['item_id']} ({r['raw'].get('published')}): "
                     f"no activation in the 12 hours before it was published")
            r["parent_event_id"] = open_acts[-1]["event_id"] if open_acts else None
            r.update(status="ended", time_precision="bound")
            r["raw"]["_ended_before"], r["raw"]["_ended_before_basis"] = bound, basis
            for a in open_acts:
                a.update(status="ended", time_precision="bound")
                a["raw"]["_ended_before"], a["raw"]["_ended_before_basis"] = bound, basis
            open_acts = []


# --------------------------------------------------------------------------- Portsmouth

def portsmouth(html: str, fetched_at: str) -> list[dict]:
    out = []
    tables = [b[1] for b in blocks(html) if b[0] == "table"]
    t = next((t for t in tables if any("CSO 10A" in c for r in t for c in r)), None)
    if t is None:
        raise RuntimeError("summary table not found on the Portsmouth CSO page")
    head = next(r for r in t if any("CSO 10A" in c for c in r))
    outfalls = [re.search(r"CSO\s+(\w+)", c).group(1) for c in head if re.search(r"CSO\s+\w+\s+Volume", c)]
    for r in t:
        if len(r) < 2 + len(outfalls) or not re.fullmatch(r"\d{4}", r[0]):
            continue
        month_txt, href = re.match(r"^(.*?)\s*(?:\[([^\]]+)\])?\s*$", r[1]).groups()
        mon = MONTHS.get(month_txt.strip().lower())
        if not mon:
            continue
        for k, oid in enumerate(outfalls):
            v = r[2 + k].strip()
            if not re.fullmatch(r"\d*\.?\d+", v) or float(v) == 0:
                continue
            placed = _placed("NH0100234", oid)
            d = date(int(r[0]), mon, 1)
            out.append(_ev("portsmouth", f"{d.strftime('%Y-%m')}:{oid}",
                           event_type="cso", status="ended",
                           outfall_id=oid, outfall_name=placed.pop("outfall_name", None),
                           **{k2: v2 for k2, v2 in placed.items() if k2 != "outfall_id"},
                           started_at=_day(d), time_precision="month", fetched_at=fetched_at,
                           material=CSO_MATERIAL, volume_gal=round(float(v) * 1_000_000), volume_text=f"{v} MG",
                           estimate_flag="unknown",
                           source_url=href or URLS["portsmouth"],
                           raw={"year": r[0], "month": month_txt.strip(), "outfall": f"CSO {oid}",
                                "volume_mg": v, "total_mg": r[2 + len(outfalls)] if len(r) > 2 + len(outfalls) else None,
                                "memo_pdf": href}))
    return out


# --------------------------------------------------------------------------- Exeter

_HM = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?\s?m\b\.?", re.I)


def _exeter_date(s: str) -> tuple[date | None, date | None]:
    s = _clean(s)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s*&\s*(\d{1,2}))?", s)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, (date(d.year, d.month, int(m.group(4))) if m.group(4) else None)
    m = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?,?\s+(\d{4})", s)
    if m:
        mon = MONTHS.get(m.group(1).lower()) or next((v for k, v in MONTHS.items() if k.startswith(m.group(1).lower()[:3])), None)
        if mon:
            d = date(int(m.group(4)), mon, int(m.group(2)))
            return d, (date(d.year, mon, int(m.group(3))) if m.group(3) else None)
    return None, None


def _exeter_times(d: date, d2: date | None, text: str) -> tuple[str | None, str | None, str]:
    hm = [(int(h) % 12 + (12 if ap.lower() == "p" else 0), int(mi)) for h, mi, ap in _HM.findall(text)]
    dur = re.search(r"(?:duration of|for)\s+(\d+)\s+minutes?", text, re.I)
    if hm:
        s = datetime(d.year, d.month, d.day, *hm[0], tzinfo=TZ)
        e = None
        if len(hm) > 1:
            ed = d2 or d
            e = datetime(ed.year, ed.month, ed.day, *hm[1], tzinfo=TZ)
            if e < s and d2 is None:
                e += timedelta(days=1)   # "10:50 pm and ended at 11:05 pm" style; past midnight
        elif dur:
            e = s + timedelta(minutes=int(dur.group(1)))
        return s.isoformat(), e.isoformat() if e else None, "minute"
    end = _day(d2) if d2 else None
    return _day(d), end, "day"


def _gallons(text: str) -> tuple[int | None, str | None, str]:
    s = _clean(text)
    if not s or not re.search(r"\d", s):
        return None, s or None, "unknown"
    if re.search(r"\d\s*-\s*\d", s):
        return None, s, "estimated"
    gal, flag = parse_volume_gal(s)
    if re.search(r"\(?est", s, re.I):
        flag = "estimated"
    return gal, s, flag


def exeter(html: str, fetched_at: str) -> list[dict]:
    out, section, seen = [], None, {}
    for kind, val in blocks(html):
        if kind == "h":
            low = val.lower()
            section = ("bypass" if "non-disinfected" in low else "cso" if "combined sewer overflow" in low
                       else "sso" if "sanitary sewer overflow" in low else None)
            continue
        if section == "bypass" and kind == "p":
            m = re.match(r"^(.{6,30}?\d{4})\s*[-–]\s*(.*)$", val)
            if not m:
                continue
            d, d2 = _exeter_date(m.group(1))
            if not d:
                continue
            desc = m.group(2)
            gm = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:\(EST\)\s*)?(?:total\s+)?(?:gallons)?\s*(?:of\s+non-disinfected|from outfall|into)", desc, re.I) \
                or re.search(r"discharge of\s+(?:approximately\s+)?([\d,]+)", desc, re.I) \
                or re.search(r"([\d,]+)\s+(?:total\s+)?gallons", desc, re.I)
            gal, vtext, flag = _gallons(gm.group(1) + " gallons") if gm else (None, None, "unknown")
            if gm and (re.search(r"approximately\s+" + re.escape(gm.group(1)), desc, re.I)
                       or re.search(re.escape(gm.group(1)) + r"\s*\(EST\)", desc, re.I)):
                flag = "estimated"
            s, e, prec = _exeter_times(d, d2, desc)
            n = seen[("bypass", d)] = seen.get(("bypass", d), 0) + 1
            slugs, _ = match_waters(desc, "nh", ["Exeter"])
            ofm = re.search(r"outfall\s*#?\s*(\d{3})", desc, re.I)
            out.append(_ev("exeter", f"bypass:{d.isoformat()}:{n}",
                           discharger_id="nh-exeter-wwtp-bypass", discharger_name="Town of Exeter WWTP",
                           event_type="plant_bypass", status="ended",
                           outfall_id=ofm.group(1) if ofm else None,
                           outfall_name="WWTP outfall 001" if ofm and ofm.group(1) == "001" else ("Wastewater Treatment Plant" if "plant" in desc.lower() else None),
                           waterbody_text="Squamscott River" if slugs else None,
                           water_slugs=slugs or ["squamscott-river-nh"], water_match="name" if slugs else "inferred",
                           started_at=s, ended_at=e, time_precision=prec, fetched_at=fetched_at,
                           material="non-disinfected treated effluent", volume_gal=gal, volume_text=vtext,
                           estimate_flag=flag, raw={"section": "Non-disinfected Discharge", "text": val}))
        elif section in ("cso", "sso") and kind == "table":
            for r in val:
                if len(r) < 3 or r[0].lower().startswith("date"):
                    continue
                d, d2 = _exeter_date(r[0])
                n = seen[(section, d)] = seen.get((section, d), 0) + 1
                if not d:
                    out.append(_ev("exeter", f"{section}:unparsed:{n}", event_type=section, fetched_at=fetched_at,
                                   raw={"section": section.upper(), "row": r}, parse_error=f"date not parsed: {r[0]!r}"))
                    continue
                gal, vtext, flag = _gallons(r[1])
                desc = r[2]
                s, e, prec = _exeter_times(d, d2, desc)
                if section == "cso":
                    placed = _placed("NH0100871", "003")
                    f = dict(outfall_id="003", outfall_name="Clemson Pond tide gate (CSO structures: " +
                             ", ".join(x for x in ("Spring St", "Water St") if x.lower() in desc.lower()) + ")"
                             if re.search(r"spring st|water st", desc, re.I) else "Clemson Pond tide gate",
                             **{k: v for k, v in placed.items() if k not in ("outfall_id", "outfall_name")})
                    material = CSO_MATERIAL
                else:
                    slugs, _ = match_waters(desc, "nh", ["Exeter"])
                    f = dict(outfall_name=desc[:120], water_slugs=slugs, water_match="name" if slugs else "none",
                             waterbody_text=next((w for w in ("Exeter River", "Little River", "Squamscott River")
                                                  if w.lower() in desc.lower()), None))
                    material = "untreated sewage"
                out.append(_ev("exeter", f"{section}:{d.isoformat()}:{n}",
                               event_type=section, status="ended", **f,
                               started_at=s, ended_at=e, time_precision=prec, fetched_at=fetched_at,
                               material=material, volume_gal=gal, volume_text=vtext, estimate_flag=flag,
                               raw={"section": section.upper(), "date": r[0], "total_gallons": r[1], "description": desc}))
    if not out:
        raise RuntimeError("no Exeter records parsed (page layout changed?)")
    return out


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    fetched_at = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    used_browser: list[str] = []
    new: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    counts = {}
    for key, fn, ext in (("nashua", nashua, "pdf"), ("manchester", manchester, "html"),
                         ("portsmouth", portsmouth, "html"), ("exeter", exeter, "html")):
        try:
            r = _get(sess, URLS[key], used_browser)
            save_raw(SOURCE_ID, r.content, f"{key}.{ext}")
            recs = _require(fn(r.content if ext == "pdf" else r.text, fetched_at), f"{key} records")
            new[key] = recs
            counts[key] = len(recs)
        except Exception as e:
            errors[key] = f"{type(e).__name__}: {e}"
    prev_file = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    if not new:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(f"{k}: {v}" for k, v in errors.items()),
                     meta={**(prev_file.get("meta") or {}),
                           **health_meta(prev_file, {}, errors, fetched_at)})
        print(f"{SOURCE_ID}: all permittees failed: {errors}", file=sys.stderr)
        return 1
    records, health = assemble(prev_file, new, errors, fetched_at)
    meta = {"urls": URLS, "counts_fetched": counts, "errors": errors or None,
            "browser_headers_used_for": used_browser or None, "advice": ADVICE_NOTE,
            "outfall_registry": "data/outfalls-new-england.json (EPA ECHO) by permit + outfall number", **health}
    path = write_events(SOURCE_ID, records, ok=True, error="; ".join(f"{k}: {v}" for k, v in errors.items()) or None,
                        meta=meta)
    print(f"{SOURCE_ID}: {counts}, errors {errors or 'none'}, {len(records)} in file -> {path}")
    return 0


def health_meta(prev_file: dict, new: dict[str, list[dict]], errors: dict[str, str], fetched_at: str) -> dict:
    """Per-permittee health: meta.permittees (all) and meta.partial_failures (failed this run)."""
    prev_meta = prev_file.get("meta") or {}
    prev_h = prev_meta.get("permittees") or {}
    prev_records = prev_file.get("records") or []
    permittees, failures = {}, {}
    for key, p in PERMITTEES.items():
        before = prev_h.get(key) or {}
        last_ok = before.get("last_ok_at")
        if last_ok is None and not prev_h and prev_file.get("ok"):
            last_ok = prev_file.get("last_ok_at")            # files written before per-permittee health
        if key in new:
            permittees[key] = {"ok": True, "last_ok_at": fetched_at, "last_attempt_at": fetched_at,
                               "error": None, "records": len(new[key])}
            continue
        mine = [r for r in prev_records if r["source_record_id"].startswith(key + ":")]
        slugs = sorted({s for r in mine for s in (r.get("water_slugs") or [])})
        err = errors.get(key, "not fetched")
        permittees[key] = {"ok": False, "last_ok_at": last_ok, "last_attempt_at": fetched_at,
                           "error": err, "records": len(mine)}
        failures[key] = {"discharger_id": p["discharger_id"], "npdes_permit": p["npdes_permit"],
                         "event_id_prefix": f"{SOURCE_ID}:{key}:", "water_slugs": slugs, "error": err,
                         "failed_at": fetched_at, "last_ok_at": last_ok}
    return {"permittees": permittees, "partial_failures": failures}


def assemble(prev_file: dict, new: dict[str, list[dict]], errors: dict[str, str], fetched_at: str) -> tuple[list[dict], dict]:
    """Merge this run's per-permittee records with the previous file; returns (records, health meta)."""
    prev = prev_file.get("records") or []
    records: list[dict] = []
    for key in PERMITTEES:
        mine_prev = [r for r in prev if r["source_record_id"].startswith(key + ":")]
        if key not in new:
            records += mine_prev                      # fetch failed: keep what we had
        elif key == "manchester":                     # page shows ~10 posts: keep older snapshots
            ids = {r["event_id"] for r in new[key]}
            records += [r for r in mine_prev if r["event_id"] not in ids] + new[key]
        else:
            records += new[key]                       # full history on the page / in the PDF
    pair_manchester(records)
    records.sort(key=lambda r: r.get("started_at") or r.get("reported_at") or "", reverse=True)
    return records, health_meta(prev_file, new, errors, fetched_at)


if __name__ == "__main__":
    sys.exit(main())
