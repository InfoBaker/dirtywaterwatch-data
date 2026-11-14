"""Missouri DNR's Water Pollution Control concern reports: the monthly reports of the environmental concerns the
Department investigated, read for the concerns typed "Bypass or Sewer Overflow", as delayed sewage reports with their
provenance (the public's report or the operator's own) and the Department's finding.

Source
  The Clean Water Commission's page (https://dnr.mo.gov/commissions-boards-councils/clean-water-commission, registry
  mo-dnr-concern-reports) links one document page a month ("Water Pollution Control Concerns Report, February 2026",
  /document-search/water-pollution-control-concerns-report-<month>-<year>); each document page links its PDF ("Water
  Pollution Control Detail Report, Concerns Investigated Between February 01, 2026 and February 28, 2026") and shows a
  "Last revised" date. The PDF is generated text (no scan) and is read with the pure-Python reader
  (ingest/nh_pdftext.py); each concern is a block: region, date received, investigation date, suspected source,
  city and county, type of concern, inspector's initials, NOV, then "Concern No.", "Concern Info" (the concerned
  party's words) and "Comments" (the Department's). Read 2026-11-14: six reports, December 2025 to May 2026 (945
  concerns; 140 typed "Bypass or Sewer Overflow"). The reports come with the Commission's meetings: December to
  February was linked for the April 8 meeting and March to May for July 15, the PDFs two to four months after the
  month they cover. Clocks kept apart: the report period, the PDF's footer date (when it was generated), the
  document page's "Last revised" date, the concern's date received and investigation date, and the incident date
  the concern gives; none of them is a publication time, so published_at stays null.

Record rules (the allegation filter: a concern is the concerned party's allegation, never the Department's
confirmation, unless the Department's comments say what it found)
  - Read: a block typed "Bypass or Sewer Overflow". Dropped: one also typed "Single Family Residence" (a private
    septic system, not a sewer), one the Department sent to a county health department or the Department of Health and
    Senior Services (outside its sewer remit: REFERRED_OUT), and one whose comments say the Department found nothing
    (NOT_FOUND: "no violations", "could not be detected", "no evidence"). Each drop is counted in the run's stats.
  - Kept, each with raw.dnr_finding: "observed" (the comments report a violation, a notice of violation, a letter of
    warning, non-compliance or an overflow seen), "operator_reported" (the comments or the concern cross-reference the
    operator's own SSO/Bypass Event System report: raw.sso_event_id), or "not_stated" (the comments say neither).
    raw.provenance is "operator" when the operator reported it and "public" otherwise; a public report carries
    raw.citizen_caution: it is the public's report, shown with the site's caution, never as the Department's finding.
  - Times (America/Chicago, dates only): started_at is the concern's "Date of Incident or Date First Noticed" when it
    gives one, else the date received (raw.start_kind "received": the overflow began on or before it); reported_at is
    the date received; raw.investigated_on the investigation date. Day precision; no end (the reports give none).
  - Place: the county from the block (raw.county); no point and no street is stored. A named creek or river the text
    says the sewage entered is the receiving water; the name only.
  - Operator: only a city, village or town the block names ("City of St. Joseph"), or a permit number (MO0000000) the
    text gives; never the suspected-source text itself (it often names people or private homes). raw.facility_kind
    says what kind of system it was where the block says (treatment facility, lagoon, mobile home park, collection
    system, pump station).
  - event_type "sso"; status unknown.

Privacy: the concern texts and comments name concerned parties, neighbours, owners, staff and private addresses. They
are read in memory only and never stored: no record, raw save or fixture holds them. data/raw keeps the parsed safe
fields of the kept and dropped blocks (concern number, region, dates, county, types, finding, water name, SSO event
id) and the PDF is never saved.
Run from pipeline/:  python -m ingest.mo_dnr_concerns [--file report.pdf --page-url URL --pdf-url URL]
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import nh_pdftext
from ingest.mo_kc_water_news import waters

SOURCE_ID = "mo-dnr-concern-reports"
INDEX = "https://dnr.mo.gov/commissions-boards-councils/clean-water-commission"
BASE = "https://dnr.mo.gov"
AUTHORITY = "Missouri Department of Natural Resources, Water Pollution Control concern report"
DOC_LINK = re.compile(r'href="(/document-search/water-pollution-control-concerns-report-[a-z]+-\d{4})"')
PDF_LINK = re.compile(r'href="([^"]+\.pdf)"', re.I)
REVISED = re.compile(r"Last revised.*?(\d{2}/\d{2}/\d{4})", re.S)
SEWER_TYPE = "bypass or sewer overflow"
PRIVATE_TYPE = "single family residence"
HEADER = re.compile(r'^(?:Water Pollution Control|Concerns Investigated|Division of Environmental|Note: "Concern|'
                    r"reflect the nature|which inspections|Date Received|Region\b)")
DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
INCIDENT = re.compile(r"Date (?:of Incident or )?(?:Date )?First Noticed:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
SSO_ID = re.compile(r"(?:SSO|Bypass)[^.]{0,80}?Event (?:ID|Number)(?: number)?(?: is)?:?\s*(\d{4,6})", re.I)
PERMIT = re.compile(r"\bMO(?:G|R)?\d{7}\b")
OBSERVED = re.compile(r"violations? (?:was |were |have been )?(?:observed|noted|found|documented|issued)|notice of "
                      r"violation|\bR?NOV\b|letter of warning|non-?compliance|observed[^.]{0,40}\b(?:overflow|discharge|"
                      r"bypass|sewage)|experiencing a[^.]{0,20}overflow|causing pollution|pollution of waters", re.I)
NOT_FOUND = re.compile(r"\bno (?:water quality )?violations?\b|no violations of|could not be (?:detected|found|located|"
                       r"confirmed)|no evidence|did not (?:see|observe|find|detect)|no issues|not observed|unfounded|"
                       r"no sewage (?:was )?(?:observed|found|present)", re.I)
REFERRED_OUT = re.compile(r"county health department|health department|\bDHSS\b|department of health and senior|"
                          r"jurisdiction of the [\w ]*county", re.I)
OPERATOR_REPORT = re.compile(r"SSO/Bypass Event System|SSO (?:report )?(?:was|has been) submitted|submitted an SSO|"
                             r"Event ID", re.I)
FACILITY_KIND = [("lagoon", r"\blagoon"), ("treatment facility", r"\bWW[TF]P?\b|WWTF|treatment (?:plant|facility)|"
                                                                  r"oxidation ditch"),
                 ("pump station", r"pump station|lift station"), ("mobile home park", r"mobile home|\bMH[PC]\b|trailer"),
                 ("collection system", r"sewer (?:main|line|system)|manhole|collection system")]


def _county_keys() -> list[tuple[str, str]]:
    doc = json.loads((common.DATA_DIR / "reference" / "mo-counties.json").read_text())
    out = []
    for c in doc["counties"]:
        name = c["county"]
        bare = re.sub(r"\s+(County|city)$", "", name)
        out.append((re.sub(r"[^a-z]", "", bare.lower()), bare))
    return sorted(set(out), key=lambda kv: -len(kv[0]))


def blocks(pdf: bytes) -> tuple[list[dict], dict]:
    """The concern blocks of one report and the report's own lines (period, footer date)."""
    rows = nh_pdftext.rows(nh_pdftext.text_items(pdf))
    meta, out, cur, mode = {}, [], None, None
    for r in rows:
        txt = " ".join(i["text"] for i in r).strip()
        m = re.search(r"([A-Z][a-z]+ \d{2}, \d{4}) and ([A-Z][a-z]+ \d{2}, \d{4})", txt)
        if m and "period" not in meta:
            meta["period"] = [datetime.strptime(x, "%B %d, %Y").date().isoformat() for x in m.groups()]
        f = re.search(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), ([A-Z][a-z]+ \d{1,2}, \d{4})\b", txt)
        if f and re.search(r"Page \d+ of \d+", txt):
            meta.setdefault("generated", datetime.strptime(f.group(1), "%B %d, %Y").date().isoformat())
            continue
        if HEADER.match(txt):
            continue
        first = r[0]
        if first["x"] < 45 and re.fullmatch(r"[A-Z]{2,5}", first["text"].strip()) and \
                any(DATE.fullmatch(i["text"].strip()) for i in r):
            cur = {"region": first["text"].strip(), "head": [r], "info": [], "comments": []}
            out.append(cur)
            mode = "head"
            continue
        if cur is None:
            continue
        if txt.startswith("Concern No."):
            cur["no"] = re.sub(r"\D", "", txt) or None
            mode = "no"
            continue
        if txt.startswith("Concern Info"):
            mode = "info"
            cur["info"].append(txt[len("Concern Info"):])
            continue
        if txt.startswith("Comments"):
            mode = "comments"
            cur["comments"].append(txt[len("Comments"):])
            continue
        if mode == "head":
            cur["head"].append(r)
        elif mode in ("info", "comments"):
            cur[mode].append(txt)
    for b in out:
        cols = defaultdict(list)
        for row in b.pop("head"):
            for i in row:
                x = i["x"]
                k = ("date" if 60 < x < 160 else "source" if 160 <= x < 350 else "type" if 350 <= x < 470
                     else "insp" if 470 <= x < 525 else "nov" if x >= 525 else "region")
                cols[k].append(i["text"].strip())
        b["dates"] = [d for d in cols["date"] if DATE.fullmatch(d)]
        b["source"] = cols["source"]
        b["type"] = re.sub(r"\s+", " ", " ".join(cols["type"])).strip()
        b["info"] = re.sub(r"\s+", " ", " ".join(b["info"])).strip()
        b["comments"] = re.sub(r"\s+", " ", " ".join(b["comments"])).strip()
    return out, meta


def _iso(m) -> str | None:
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except (ValueError, AttributeError):
        return None


def county_of(source: list[str], keys) -> str | None:
    s = re.sub(r"[^a-z]", "", "".join(source).lower())
    return next((bare for k, bare in keys if k and s.endswith(k)), None)


_PLACES: set[str] = set()


def mo_places() -> set[str]:
    """Missouri's sewer-permit towns as EPA names them (data/outfalls-plants-us.json: the city field and "X, CITY OF")."""
    if not _PLACES:
        doc = json.loads((common.DATA_DIR / "outfalls-plants-us.json").read_text())
        for r in doc["outfalls"]:
            if r.get("state") != "MO":
                continue
            for v in (r.get("city"), re.sub(r",\s*(?:CITY|VILLAGE|TOWN) OF.*$", "", r.get("permit_name") or "")):
                if v:
                    _PLACES.add(re.sub(r"[^A-Z ]", "", v.upper().replace("SAINT", "ST")).strip())
    return _PLACES


def town_of(source: list[str]) -> str | None:
    """'City of Marble Hill' from the source pieces ('City of Marble', 'Hill', ...): the longest run of words after
    "City of", "Village of" or "Town of" (up to three, across the next pieces) that is a Missouri sewer-permit town."""
    places = mo_places()
    for i, piece in enumerate(source):
        m = re.match(r"^(City|Village|Town) of\s+(.*)$", piece.strip())
        if not m:
            continue
        words = (m.group(2) + " " + " ".join(source[i + 1:i + 3])).split()
        for n in (3, 2, 1):
            cand = " ".join(words[:n])
            key = re.sub(r"[^A-Z ]", "", cand.upper()).strip()
            if key in places:
                return f"{m.group(1)} of {cand}"
    return None


def finding(b: dict) -> tuple[str, str]:
    """(decision, finding): decision keep / drop_private / drop_referred / drop_not_found."""
    text = f"{b['info']} {b['comments']}"
    if PRIVATE_TYPE in b["type"].lower():
        return "drop_private", "private septic system"
    op = bool(SSO_ID.search(text) or OPERATOR_REPORT.search(b["comments"]))
    obs = bool(OBSERVED.search(b["comments"])) and not re.search(r"\bno (?:\w+ )?violations", b["comments"], re.I)
    if op:
        return "keep", "operator_reported"
    if obs:
        return "keep", "observed"
    if NOT_FOUND.search(b["comments"]):
        return "drop_not_found", "not found"
    if REFERRED_OUT.search(b["comments"]):
        return "drop_referred", "referred to a health department"
    return "keep", "not_stated"


def record(b: dict, meta: dict, keys, at: str) -> tuple[str, dict | None, dict]:
    """(decision, record or None, the safe fields kept in data/raw)."""
    decision, find = finding(b)
    text = f"{b['info']} {b['comments']}"
    received = _iso(DATE.search(b["dates"][0])) if b["dates"] else None
    investigated = _iso(DATE.search(b["dates"][1])) if len(b["dates"]) > 1 else None
    inc = INCIDENT.search(b["info"])
    incident = _iso(inc) if inc else None
    sso = SSO_ID.search(text)
    county = county_of(b["source"], keys)
    town = town_of(b["source"])
    permit = PERMIT.search(text)
    kind = next((k for k, rx in FACILITY_KIND if re.search(rx, " ".join(b["source"]) + " " + b["info"], re.I)), None)
    ws = waters(text)
    safe = {"concern_no": b.get("no"), "region": b["region"], "received": received, "investigated": investigated,
            "incident_date": incident, "county": county, "types": b["type"], "decision": decision, "finding": find,
            "sso_event_id": sso.group(1) if sso else None, "waters_named": ws, "facility_kind": kind,
            "report_period": meta.get("period"), "report_generated": meta.get("generated")}
    if decision != "keep" or not b.get("no") or not received:
        return decision if b.get("no") and received else "drop_unreadable", None, safe
    start = incident if incident and incident <= received else received
    operator = town
    raw = {"state": "MO", "time_zone": "America/Chicago", "concern_no": b["no"], "region": b["region"],
           "county": f"{county} County" if county and county != "St. Louis" else None,
           "counties": ["St. Louis County", "St. Louis city"] if county == "St. Louis" else None,
           "investigated_on": investigated, "incident_date": incident, "concern_types": b["type"],
           "dnr_finding": find, "provenance": "operator" if find == "operator_reported" else "public", "_placement": "named_water_only",
           "citizen_caution": find != "operator_reported",
           "sso_event_id": safe["sso_event_id"], "permit_named": permit.group(0) if permit else None,
           "facility_kind": kind, "waters_named": ws, "report_period": meta.get("period"),
           "report_generated": meta.get("generated"), "page_last_revised": meta.get("last_revised"),
           "page_url": meta.get("page_url"),
           "start_kind": "incident" if start == incident else "received",
           "start_basis": ("the incident or first-noticed date the concern gives" if start == incident else
                           "the date the Department received the concern; the overflow began on or before it"),
           "finding_basis": {"operator_reported": "the Department's comments or the concern cross-reference the "
                                                  "operator's own SSO/Bypass Event System report",
                             "observed": "the Department's comments report what it found (a violation, a notice or "
                                         "letter, or an overflow seen)",
                             "not_stated": "the concerned party's report; the Department's comments state no finding"}[find],
           "time_basis": "dates only, Central time; no end is given"}
    rec = event(source_id=SOURCE_ID, source_record_id=b["no"], event_type="sso", status="unknown",
                discharger_name=operator, npdes_permit=raw["permit_named"],
                waterbody_text=ws[0] if ws else None, started_at=start, time_precision="day",
                reported_at=received, published_at=None, fetched_at=at, material="sewage",
                authority=AUTHORITY + (" (the operator's report)" if find == "operator_reported" else
                                       " (the Department's finding)" if find == "observed" else
                                       " (a public concern; not confirmed by the Department)"),
                source_url=meta.get("pdf_url"), raw=raw)
    return decision, rec, safe


def run(reports: list[tuple[bytes, dict]], prev: list[dict], at: str) -> tuple[list[dict], dict, list[dict]]:
    keys = _county_keys()
    recs = {r["event_id"]: r for r in prev}
    stats, safe_rows, withdrawn = Counter(), [], []
    parsed = []
    for pdf, meta in reports:
        bs, m2 = blocks(pdf)
        parsed.append((bs, {**meta, **m2}))
    for bs, meta in sorted(parsed, key=lambda x: (x[1].get("period") or [""])[0]):   # older report periods first
        stats["concerns"] += len(bs)
        for b in bs:
            if SEWER_TYPE not in b["type"].lower():
                continue
            stats["sewer_overflow_type"] += 1
            decision, rec, safe = record(b, meta, keys, at)
            stats[decision] += 1
            safe_rows.append(safe)
            if rec is None and b.get("no") and f"{SOURCE_ID}:{b['no']}" in recs:
                # a later report that finds the concern unsupported (or outside the sewer remit) withdraws the
                # record an earlier report kept (Astra 2026-11-14 P1-7); a later keep restores it
                gone = recs.pop(f"{SOURCE_ID}:{b['no']}")
                withdrawn.append({"concern_no": b["no"], "decision": decision, "was": gone["raw"].get("dnr_finding"),
                                  "report_period": meta.get("period")})
                stats["withdrawn"] += 1
            if rec:
                stats["kept_" + rec["raw"]["dnr_finding"]] += 1
                old = recs.get(rec["event_id"])
                rec["raw"]["first_seen_at"] = (old or {}).get("raw", {}).get("first_seen_at") or at
                recs[rec["event_id"]] = rec
    for r in recs.values():
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    st = dict(stats)
    st["withdrawn_concerns"] = withdrawn
    return out, st, safe_rows


def fetch(prev: list[dict]) -> list[tuple[bytes, dict]]:
    """Every report the Commission's page links whose PDF (by URL and "Last revised") was not read before."""
    seen = {(r["source_url"], r["raw"].get("page_last_revised")) for r in prev}
    idx = requests.get(INDEX, headers=HEADERS, timeout=(20, 120))
    idx.raise_for_status()
    out = []
    for path in dict.fromkeys(DOC_LINK.findall(idx.text)):
        page = requests.get(BASE + path, headers=HEADERS, timeout=(20, 120))
        page.raise_for_status()
        pdfs = [u for u in PDF_LINK.findall(page.text) if "/files/" in u]
        if not pdfs:
            continue
        pdf_url = html.unescape(pdfs[0])
        pdf_url = pdf_url if pdf_url.startswith("http") else BASE + pdf_url
        rev = REVISED.search(page.text)
        last_rev = (datetime.strptime(rev.group(1), "%m/%d/%Y").date().isoformat() if rev else None)
        if (pdf_url, last_rev) in seen:
            continue
        pdf = requests.get(pdf_url, headers=HEADERS, timeout=(20, 300))
        pdf.raise_for_status()
        out.append((pdf.content, {"page_url": BASE + path, "pdf_url": pdf_url, "last_revised": last_rev}))
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            reports = [(Path(argv[argv.index("--file") + 1]).read_bytes(),
                        {"page_url": argv[argv.index("--page-url") + 1] if "--page-url" in argv else None,
                         "pdf_url": argv[argv.index("--pdf-url") + 1] if "--pdf-url" in argv else None,
                         "last_revised": argv[argv.index("--last-revised") + 1] if "--last-revised" in argv else None})]
        else:
            reports = fetch(prev)
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats, safe = run(reports, prev, now_iso())
    if safe:
        save_raw(SOURCE_ID, json.dumps(safe, ensure_ascii=False, indent=1), "json")
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": INDEX, **stats, "reports_read": len(reports),
        "credit": "Missouri Department of Natural Resources, Water Pollution Control concern reports",
        "caveat": ("Concerns the Department investigated, published monthly and two to four months late. A concern is "
                   "the concerned party's report unless the Department's comments say what it found or the operator "
                   "reported the overflow itself; concerns the Department found unsupported are not shown."),
        "cadence": "daily; a report is read once (again only when its page's Last revised date changes)"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
