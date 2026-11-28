"""Springfield Water and Sewer Commission's monthly CSO reports, January 2019 to April 2023 -> data/build/events/ma-springfield-archive.json

Source (registry ma-springfield-archive)
  The commission's "CSO Data Archive" page, https://springfieldalerts.com/Suez/index.php/cso-data-archive/, links one
  PDF per month (January 2019 to April 2023) and an annual sheet per year (2019 to 2022). A monthly report is one page:
  per outfall ("CSO 007" to "CSO 049", 015A and 015B apart, 036 or 036A, the plant's 042 from July 2021) the number of
  overflow events, the total overflow volume in gallons and the overflow duration, then a Total row. Its footnote
  defines an event: "A storm event is any period of precipitation which is preceded and followed by 24 hours of dry
  weather". The duration column is headed "(H.M)" in 2019 and 2020 and "(Hours)" from 2021; both are carried as printed.
  The page is static (nothing after April 2023). October 2021 has no file: the commission's link to it is broken.

The transcript (data/reference/ma-springfield-cso-archive-2019-2023.json)
  The hourly refresh has no PDFs, so this module reads only a committed transcript, written once by
  `python -m ingest.ma_springfield_archive --extract RAW_DIR` from the PDFs (pypdf): per month the file's address, its
  Internet Archive capture (time stamp and SHA-1 digest, each PDF checked against it) or, for January to April 2023,
  which the Internet Archive does not hold, the reading of the commission's own page on 2026-11-28 (SHA-256 and size);
  the rows; the Total row; and the check that the rows add up to it (events and gallons exactly, hours within the
  rounding of the rows). A month that does not add up stops the extraction; HAND_CORRECTIONS lists any row corrected
  by hand (none). The annual sheets are transcribed beside the months (events and gallons per outfall, gallons per
  month; they give no hours).

October 2021 (computed)
  Per outfall: the 2021 annual sheet's events and gallons minus the sum of the other eleven monthly reports. No hours
  (the annual sheet gives none). The record says so (raw.computed, raw.volume_method, raw.events_method). An outfall
  whose difference is negative is not published for the month (meta.computed_not_published). The annual sheet writes
  CSO 036A and CSO 037A where the monthly reports write CSO 036 (or 036A) and CSO 037: one outfall each, joined.

Records (EPA monthly DMR shape, ingest/echo_cso_dmr_monthly.py)
  One per outfall per month with at least one event: event_type cso, status ended, started_at the first and ended_at
  the last day of the month, time_precision month (build/status.py monthly_mark: the "monthly" mark, never red or
  yellow), reported_at null and published_at null (the reports state neither; the Internet Archive's capture time is
  only a "no later than" date, kept in raw). volume_gal the month's total for the outfall as the commission reports it;
  volume_text "N discharge events; H hours; G gallons". A month with zero events at an outfall is no record (kept in
  the transcript only; grey means no report). Outfall ids through ingest/ma_springfield_aquasight.py's CROSSWALK
  (CSO 010 -> SPR010); the monthly reports' "CSO 036" is the outfall the commission's annual sheets and map name
  CSO 036A (raw._outfall_note). Place: ingest/mail/ma_common.place, as the map's records are placed.

Overlap with event-level records
  From 2022-03-19 the commission's map log (ma-springfield-aquasight) and from July 2022 MassDEP's portal (ma-massdep)
  hold the same overflows one by one. The project's rule for a monthly total beside event records of the same permit
  and outfall (EPA's monthly DMRs beside the portal since 2024) is that they stand side by side: a month-precision
  record is a total, never an event (build/charts.py is_total; build/rain_history.py skips it), and its "monthly" mark
  ranks below every red, yellow or unresolved status (build/status.py RANK; docs/plan.md section 2.x). So every month
  is emitted; meta.overlap says which months have event-level records too.

Failures: a missing or unreadable transcript, or a month in it that does not add up: ok=False, the previous records
kept.
Run from pipeline/:  python -m ingest.ma_springfield_archive [--extract RAW_DIR]
Cadence: hourly with the refresh (Massachusetts is live); it reads one committed file and asks nothing of the network.
"""
from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import json
import re
import sys
from pathlib import Path

from common import DATA_DIR, error_text, event, now_iso, write_events, write_json
from ingest import ma_springfield_aquasight as A

SOURCE_ID = "ma-springfield-archive"
REFERENCE = DATA_DIR / "reference" / "ma-springfield-cso-archive-2019-2023.json"
PAGE_URL = "https://springfieldalerts.com/Suez/index.php/cso-data-archive/"
PERMIT = A.PERMIT
DISCHARGER_ID = A.DISCHARGER_ID
DISCHARGER = A.DISCHARGER
AUTHORITY = "Springfield Water and Sewer Commission (monthly CSO reports)"
CREDIT = "Springfield Water and Sewer Commission, monthly CSO reports (CSO Data Archive)"
SPEC = {**A.SPEC, "source_id": SOURCE_ID}
FOOTNOTE = ("*A storm event is any period of precipitation which is preceded and followed by 24 hours of dry weather")
EVENT_DEFINITION = ("The reports count overflow events per storm: \"A storm event is any period of precipitation which "
                    "is preceded and followed by 24 hours of dry weather\" (the reports' footnote).")
COMPUTED_MONTH = "2021-10"
COMPUTED_VOLUME_METHOD = ("Computed by us: the outfall's 2021 total on the commission's annual sheet minus the sum of "
                          "its other eleven monthly reports for 2021 (the commission's October 2021 report is not "
                          "online)")
COMPUTED_EVENTS_METHOD = ("Computed by us the same way: the annual sheet's 2021 event count minus the eleven other "
                          "monthly reports' counts")
# event-level records of the same permit and outfalls (meta.overlap)
EVENT_LEVEL = [{"source_id": "ma-springfield-aquasight", "from": "2022-03-19",
                "what": "the commission's CSO map log, one record per overflow"},
               {"source_id": "ma-massdep", "from": "2022-07",
                "what": "MassDEP's public notification portal, one record per overflow"}]
# the annual sheets' and some monthly reports' spellings of one outfall -> the spelling the crosswalk knows
ALIASES = {"CSO036": "CSO036A", "CSO037A": "CSO037"}
# rows corrected by hand in the transcript: none (every row is as extracted)
HANDCORRECTIONS: list[dict] = []
# Months whose own Total row differs from the sum of their rows, as printed by the commission (the rows are kept as
# printed; nothing is corrected). Each value is the printed total minus the rows' sum; the check passes only for
# exactly this difference, so a new one still stops the extraction. The extraction writes each into its month
# (known_difference), and the hourly run checks the transcript against what the transcript itself lists. For the
# 1-gallon months the annual sheet's month line equals the printed total (March 2019 apart, whose line differs by more,
# as several 2019 lines do: research/ma/springfield-archive-comparison.md).
GALLON_ROUNDING = "the Total row differs from the rows by 1 gallon in the commission's report (rounding)"
KNOWN_DIFFERENCES: dict[str, dict] = {
    "2019-03": {"volume_gal": 1, "why": GALLON_ROUNDING},
    "2019-04": {"volume_gal": -1, "why": GALLON_ROUNDING},
    "2019-05": {"volume_gal": 1, "why": GALLON_ROUNDING},
    "2019-09": {"events": -2.25, "why": ("the Total row prints 38.75 events, not a whole number; the rows give 41 "
                                         "(gallons and hours add up)")},
    "2021-09": {"volume_gal": -1, "why": GALLON_ROUNDING},
    "2021-11": {"volume_gal": -1, "why": GALLON_ROUNDING},
    "2022-11": {"volume_gal": 1, "why": GALLON_ROUNDING},
}
MONTHS = list(calendar.month_name)[1:]
ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}


class TranscriptError(Exception):
    """A transcript that cannot be used (a month that does not add up, a missing field)."""


# ---------------------------------------------------------------- outfalls

def key_of(label) -> str:
    """'CSO 036' / 'CSO-042' / 'CSO 037A' -> the crosswalk's asset spelling ('CSO036A', 'CSO042', 'CSO037')."""
    a = re.sub(r"[\s-]+", "", str(label or "")).upper()
    return ALIASES.get(a, a)


def outfall_of(label) -> tuple[str | None, int | None, str]:
    """(portal outfall id or None, number, suffix) through the map's crosswalk."""
    return A.outfall_of(key_of(label))


# ---------------------------------------------------------------- checks

def hours_tolerance(rows: list[dict]) -> float:
    """Each row's hours are rounded to a tenth: the sum may differ from the Total by half a tenth per row with hours."""
    n = sum(1 for r in rows if r.get("hours"))
    return round(0.05 * n + 0.05, 2)


def check_month(rows: list[dict], total: dict, known: dict | None = None, where: str = "") -> dict:
    """Rows against the Total row: events and gallons exactly, hours within rounding. known: the differences printed
    in the source itself (KNOWN_DIFFERENCES[month]), each {field: printed total minus the rows' sum}; a difference
    passes only when it is exactly the one listed. Raises TranscriptError."""
    known = known or {}
    ev = sum(r["events"] for r in rows)
    gal = sum(r["volume_gal"] for r in rows)
    out = {"events": [ev, total.get("events")], "volume_gal": [gal, total.get("volume_gal")]}
    bad, accepted = [], []
    for k in ("events", "volume_gal"):
        if out[k][0] == out[k][1]:
            continue
        diff = None if out[k][1] is None else round(out[k][1] - out[k][0], 6)
        (accepted if k in known and diff == known[k] else bad).append(k)
    if all(r.get("hours") is not None for r in rows) and total.get("hours") is not None:
        h = round(sum(r["hours"] for r in rows), 1)
        tol = hours_tolerance(rows)
        out["hours"] = [h, total["hours"], tol]
        if abs(h - total["hours"]) > tol + 1e-9:
            bad.append("hours")
    unused = sorted(set(known) - {"why"} - set(accepted))
    if bad or unused:
        raise TranscriptError(f"{where + ': ' if where else ''}rows do not add up to the Total row "
                              f"({', '.join(bad + unused)}): {out}")
    out["ok"] = True
    if accepted:
        out["source_difference"] = {**{k: known[k] for k in accepted}, "why": known.get("why")}
    return out


def validate(doc: dict) -> list[str]:
    """Every month of the transcript checked again (the reported months against their Total row, the computed month
    against the annual sheet). Returns the months; raises TranscriptError."""
    months = doc.get("months") if isinstance(doc, dict) else None
    if not isinstance(months, dict) or not months:
        raise TranscriptError("the transcript has no months")
    for ym, m in sorted(months.items()):
        if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", ym):
            raise TranscriptError(f"{ym}: not a month")
        rows = m.get("rows")
        if not isinstance(rows, list) or not rows:
            raise TranscriptError(f"{ym}: no rows")
        for r in rows:
            if not isinstance(r.get("events"), int) or r["events"] < 0 or not isinstance(r.get("volume_gal"), int) \
                    or r["volume_gal"] < 0:
                raise TranscriptError(f"{ym}: a row without a whole, non-negative count and volume")
        if m.get("computed"):
            if not m.get("method"):
                raise TranscriptError(f"{ym}: computed with no method stated")
            continue
        check_month(rows, m.get("total_row") or {}, m.get("known_difference"), where=ym)
    return sorted(months)


# ---------------------------------------------------------------- records

def plural(n, word: str) -> str:
    return f"{n:g} {word}{'' if n == 1 else 's'}"


def month_bounds(ym: str) -> tuple[str, str]:
    y, m = int(ym[:4]), int(ym[5:])
    return f"{ym}-01", f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


def month_text(ym: str) -> str:
    return f"{MONTHS[int(ym[5:]) - 1]} {ym[:4]}"


def place_of(ctx: dict, oid: str | None, num: int | None, suf: str, water: str | None):
    """(lat, lon, coord_source, coords note, outfall name, slugs, water_match, water note), as the map's records."""
    from ingest import ma_massdep as M
    from ingest.mail.ma_common import place
    lay = echo = None
    if oid:
        lay, echo, slugs, wmatch, wnote = place(ctx, SPEC, PERMIT, num, suf, water)
    else:
        slugs, wmatch, wnote = M.resolve_water([("report", water)], SPEC["town"], None,
                                               ctx.get("crosswalk") or {}, ctx.get("waters") or {})
    if lay and lay.get("lat") is not None:
        return (round(lay["lat"], 6), round(lay["lon"], 6), "outfall_layer",
                f"MassDEP CSOs layer DEP_OUTFL_ {lay['dep_id']} (locations are estimates)", lay.get("address"),
                slugs, wmatch, wnote)
    if echo and echo.get("lat") is not None:
        return (echo["lat"], echo["lon"], "outfall_layer",
                f"EPA ECHO CSO inventory {echo['npdes_permit']} outfall {echo['outfall']}", None, slugs, wmatch, wnote)
    return None, None, None, None, None, slugs, wmatch, wnote


def to_record(ym: str, m: dict, row: dict, doc: dict, ctx: dict, fetched_at: str) -> dict:
    label = row["outfall"]
    oid, num, suf = outfall_of(label)
    start, end = month_bounds(ym)
    water = row.get("watershed") or (doc.get("watersheds") or {}).get(key_of(label))
    computed = bool(m.get("computed"))
    figures = not computed or bool(row.get("figures_published"))
    raw = {"month": ym, "outfall_as_printed": label, "watershed_as_printed": row.get("watershed"),
           "event_definition": EVENT_DEFINITION,
           "report_kind": "Computed from the annual sheet" if computed else "Monthly overflow report",
           "note": ("monthly figure computed by us from the commission's reports, not an individual event" if computed
                    else "monthly total reported by the commission, not an individual event"), "state": "MA",
           "_channel": "web"}
    if figures:
        raw.update({"events": row["events"], "volume_gal": row["volume_gal"], "hours": row.get("hours")})
    if row.get("hours") is not None:
        raw["duration_label"] = m.get("duration_label")
        raw["duration_text"] = (f"{row['hours']:.1f} hours" if m.get("duration_label") == "Hours" else
                                f"{row['hours']:.1f} (printed under \"Overflow Duration ({m.get('duration_label')})\")")
    if not row.get("watershed") and water:
        raw["_water_basis"] = "the receiving water the commission's annual sheet gives for this outfall"
    if key_of(label) != re.sub(r"[\s-]+", "", label).upper():
        named = f"{key_of(label)[:3]} {key_of(label)[3:]}"
        raw["_outfall_note"] = (f"the annual sheet prints {label}; the monthly reports and the commission's map name "
                                f"this outfall {named}" if computed else
                                f"the report prints {label}; the commission's annual sheets and map name this outfall "
                                f"{named}")
    if not oid:
        raw["_outfall_note"] = "not in the crosswalk to the portal's outfall ids: the report's own id is kept"
    file_ = m.get("file") or {}
    if computed:
        meth = m["method"]
        raw.update({"computed": True, "events_method": meth["events"],
                    "volume_method": meth["volume"] if figures else (meth["volume"] + ". " + meth["withheld"]),
                    "computed_difference": {k: row[k] for k in ("events", "volume_gal", "annual_events",
                                                                "annual_volume_gal", "other_months_events",
                                                                "other_months_volume_gal")},
                    "volume_basis": (f"2021 annual sheet {row['annual_volume_gal']:,} gallons minus "
                                     f"{row['other_months_volume_gal']:,} gallons in the other eleven monthly reports"),
                    "events_basis": (f"2021 annual sheet {row['annual_events']} events minus "
                                     f"{row['other_months_events']} in the other eleven monthly reports"),
                    "revisions": m.get("revisions"), "inputs": m.get("inputs")})
        source_url = m["inputs"]["annual_sheet"]
    else:
        raw["file"] = {k: file_.get(k) for k in ("name", "url", "sha256", "bytes", "read_at") if file_.get(k)}
        cap = file_.get("capture")
        if cap:
            raw["capture"] = cap
            raw["available_no_later_than"] = cap.get("date")
        source_url = file_.get("url") or PAGE_URL
    raw["archive_page"] = PAGE_URL
    lat, lon, csrc, cnote, oname, slugs, wmatch, wnote = place_of(ctx, oid, num, suf, water)
    if cnote:
        raw["_coords"] = cnote
    if wnote:
        raw["_water"] = wnote
    if figures:
        how = " (computed)" if computed else ""
        parts = [plural(row["events"], "discharge event") + how]
        if row.get("hours") is not None:
            parts.append(raw["duration_text"])
        parts.append(f"{row['volume_gal']:,} gallons{how}")
        vtext, vgal = "; ".join(parts), row["volume_gal"]
    else:
        vtext, vgal = ("computed from the commission's 2021 annual sheet; count and gallons not given", None)
    return event(
        source_id=SOURCE_ID, source_record_id=f"{PERMIT}:{oid or key_of(label)}:{ym}", event_type="cso",
        status="ended", discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=PERMIT,
        outfall_id=oid or key_of(label), outfall_name=oname, waterbody_text=water, water_slugs=slugs,
        water_match=wmatch, lat=lat, lon=lon, coord_source=csrc,
        started_at=start, ended_at=end, time_precision="month", reported_at=None, published_at=None,
        source_updated_at=None, fetched_at=fetched_at, material="combined sewage and stormwater",
        volume_gal=vgal, volume_text=vtext, estimate_flag="unknown",
        authority=AUTHORITY, source_url=source_url, raw=raw,
    )


def build(doc: dict, ctx: dict, fetched_at: str) -> tuple[list[dict], dict]:
    """(records, counts) from a validated transcript: one record per outfall-month with events, none for zero rows."""
    recs, zero, latest = [], 0, {}
    for ym, m in sorted(doc["months"].items()):
        for row in m["rows"]:
            oid = outfall_of(row["outfall"])[0] or key_of(row["outfall"])
            k = f"{PERMIT}|{oid}"
            if k not in latest or ym > latest[k]["month"]:
                latest[k] = {"month": ym, "discharged": row["events"] > 0 or row["volume_gal"] > 0,
                             "events": row["events"], "received_at": None}
            if row["events"] <= 0:
                zero += 1
                continue
            recs.append(to_record(ym, m, row, doc, ctx, fetched_at))
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, {"zero_rows": zero, "latest_month_by_outfall": dict(sorted(latest.items()))}


def overlap(months: list[str]) -> dict:
    """Which months also have event-level records of the same permit (meta only; nothing is dropped)."""
    out = []
    for src in EVENT_LEVEL:
        frm = src["from"][:7]
        cov = [m for m in months if m >= frm]
        out.append({**src, "months": [cov[0], cov[-1]] if cov else None, "count": len(cov)})
    return {"rule": ("monthly totals stand beside event-level records of the same permit and outfall: a total is "
                     "never counted as an event and its monthly mark ranks below every red, yellow or unresolved "
                     "status (build/charts.py is_total; build/status.py RANK)"), "event_level_sources": out}


def run(reference: Path = REFERENCE, out: Path | None = None, ctx: dict | None = None) -> int:
    fetched_at = now_iso()
    try:
        doc = json.loads(Path(reference).read_text())
        months = validate(doc)
    except (OSError, ValueError, TranscriptError, KeyError, TypeError) as e:
        why = f"the transcript {Path(reference).name} cannot be used ({error_text(e)})"
        write_events(SOURCE_ID, [], ok=False, error=why, path=out)
        print(f"{SOURCE_ID}: FAILED {why}", file=sys.stderr)
        return 1
    if ctx is None:
        from ingest import operator_mail as O
        ctx = O.ma_context({"springfield": SPEC})
    recs, counts = build(doc, ctx, fetched_at)
    comp = doc["months"].get(COMPUTED_MONTH) or {}
    meta = {"registry_ids": [SOURCE_ID], "url": PAGE_URL, "credit": CREDIT, "reference": REFERENCE.name,
            "months": [months[0], months[-1]], "months_read": len(months), "records": len(recs),
            "zero_event_rows": counts["zero_rows"], "computed_months": [COMPUTED_MONTH] if comp.get("computed") else [],
            "computed_not_published": comp.get("not_published") or [],
            "hand_corrections": doc.get("hand_corrections") or [], "event_definition": EVENT_DEFINITION,
            "latest_month_by_outfall": counts["latest_month_by_outfall"], "overlap": overlap(months),
            "crosswalk": A.crosswalk_check(ctx), "covers_permits": [PERMIT], "statewide": False}
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} outfall-months with events from {len(months)} months "
          f"({counts['zero_rows']} zero rows not records) -> {path}")
    return 0


# ---------------------------------------------------------------- the one-time extraction (needs the PDFs and pypdf)

ROW_RE = re.compile(r"^(CSO[ -]\d{3}[A-Z]?)\s+(?:((?:Connecticut|Mill|Chicopee) River)\s+)?(\d+)\s+([\d,]+)\s+"
                    r"(\d+(?:\.\d+)?)(?:\s|$)")
TOTAL_RE = re.compile(r"^Total\s+(\d[\d,]*(?:\.\d+)?)\s+([\d,]+)\s+(\d+(?:\.\d+)?)(?:\s|$)")
TITLE_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d\d)\b", re.I)
ANNUAL_ROW_RE = re.compile(r"^(CSO \d{3}[A-Z]?)(?: WWTF)?\s+((?:Connecticut|Mill|Chicopee) River)\s+(\d+)\s+([\d,]+)")
ANNUAL_TOTAL_RE = re.compile(r"^System Total = ([\d,]+)\s+([\d,]+)")
ANNUAL_MONTH_RE = re.compile(r"^(" + "|".join(MONTHS) + r")\s+\d+(?:\.\d+)?\s+([\d,]+)")
LONG_NAME_RE = re.compile(r"^(\d\d)-([A-Za-z]+)-(20\d\d)-Overflow-Report\.pdf$")
SHORT_NAME_RE = re.compile(r"^CSO-([A-Z][a-z]{2})-(20\d\d)\.pdf$")


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def pdf_text(path: Path) -> str:
    """The PDF's text, no-break spaces as spaces and Unicode hyphens as "-" (the 2022 reports use both)."""
    import pypdf     # the extraction only; the hourly run never imports it
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(str(path)).pages)
    return text.replace("\u00a0", " ").replace("\u2010", "-").replace("\u2011", "-")


def sha1_b32(path: Path) -> str:
    return base64.b32encode(hashlib.sha1(path.read_bytes()).digest()).decode()


def read_index(raw_dir: Path) -> dict:
    """wayback-index.txt: basename -> {url, timestamp, digest, length}."""
    out = {}
    for line in (raw_dir / "wayback-index.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 4:
            url, ts, dig, ln = parts[:4]
            out[url.rsplit("/", 1)[-1]] = {"url": url, "timestamp": ts, "digest": dig, "length": int(ln)}
    return out


def file_entry(path: Path, idx: dict) -> dict:
    e = idx.get(path.name)
    if not e:
        raise TranscriptError(f"{path.name}: not in the Internet Archive index")
    if sha1_b32(path) != e["digest"]:      # the index's length is the archive record's, not the file's
        raise TranscriptError(f"{path.name}: does not match its Internet Archive digest")
    ts = e["timestamp"]
    return {"name": path.name, "url": e["url"], "bytes": path.stat().st_size,
            "capture": {"service": "Internet Archive", "timestamp": ts, "sha1_base32": e["digest"],
                        "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
                        "url": f"https://web.archive.org/web/{ts}/{e['url']}"}}


def month_of_file(name: str) -> str | None:
    m = SHORT_NAME_RE.match(name)
    if m and m.group(1) in ABBR:
        return f"{m.group(2)}-{ABBR[m.group(1)]:02d}"
    m = LONG_NAME_RE.match(name)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}"
    return None


def parse_month(text: str, ym: str) -> dict:
    """A monthly report's rows, Total row and duration label; the title must name the file's month."""
    t = TITLE_RE.search(text)
    if not t or f"{t.group(2)}-{MONTHS.index(t.group(1).title()) + 1:02d}" != ym:
        raise TranscriptError(f"{ym}: the report's title does not name this month")
    rows, total, seen = [], None, set()
    for line in text.splitlines():
        line = line.strip()
        m = ROW_RE.match(line)
        if m:
            label = re.sub(r"^CSO[ -]", "CSO ", m.group(1))
            if label in seen:
                raise TranscriptError(f"{ym}: {label} twice")
            seen.add(label)
            rows.append({"outfall": label, "watershed": m.group(2), "events": int(m.group(3)),
                         "volume_gal": _int(m.group(4)), "hours": float(m.group(5))})
            continue
        m = TOTAL_RE.match(line)
        if m and total is None:
            ev = m.group(1).replace(",", "")
            total = {"events": float(ev) if "." in ev else int(ev), "volume_gal": _int(m.group(2)),
                     "hours": float(m.group(3))}
    if total is None:
        raise TranscriptError(f"{ym}: no Total row")
    lab = "H.M" if "(H.M)" in text else "Hours" if "(Hours)" in text else None
    if lab is None:
        raise TranscriptError(f"{ym}: no duration heading")
    if FOOTNOTE not in " ".join(text.split()):
        raise TranscriptError(f"{ym}: the event footnote is missing")
    return {"rows": rows, "total_row": total, "duration_label": lab}


def parse_annual(text: str, year: str) -> dict:
    rows, months, total = [], {}, None
    for line in text.splitlines():
        line = line.strip()
        m = ANNUAL_ROW_RE.match(line)
        if m:
            rows.append({"outfall": m.group(1), "watershed": m.group(2), "events": int(m.group(3)),
                         "volume_gal": _int(m.group(4))})
            continue
        m = ANNUAL_TOTAL_RE.match(line)
        if m:
            total = {"events": _int(m.group(1)), "volume_gal": _int(m.group(2))}
            continue
        m = ANNUAL_MONTH_RE.match(line)
        if m:
            months[f"{year}-{MONTHS.index(m.group(1)) + 1:02d}"] = _int(m.group(2))
    if total is None or len(months) != 12 or not rows:
        raise TranscriptError(f"annual {year}: the sheet was not read whole")
    return {"rows": rows, "system_total": total, "monthly_volume_gal": months,
            "check": {"rows_events": sum(r["events"] for r in rows), "rows_volume_gal": sum(r["volume_gal"] for r in rows),
                      "months_volume_gal": sum(months.values())}}


def _names(months: dict) -> str:
    """{"2021-05": ..., "2021-07": ...} -> "May and July" (three or more: "May, July and August")."""
    n = [MONTHS[int(m[5:]) - 1] for m in sorted(months)]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " and " + n[-1]


def compute_october(months: dict, annual: dict) -> dict:
    """October 2021 per outfall from the 2021 annual sheet and the other eleven monthly reports.

    The difference per outfall (the sheet's 2021 events and gallons minus the other months') would be October's if the
    sheet carried the monthly reports' figures. It does not quite: its month lines exceed the reports' Total rows for
    some months (revisions: in 2021 May by 11,554,000 gallons, July by 6,944,000, August by 149,000). A revision equal
    to one outfall's whole difference is that outfall's, not October's (May: CSO 024, whose May report shows 0; July:
    CSO 042, absent from the July report). What remains unplaced may sit in any outfall's difference. So an outfall is
    published for October only when its gallons exceed the unplaced remainder and it has an event left: it certainly
    discharged in October. Its count and gallons are published only when nothing is unplaced; otherwise the record
    says the outfall discharged and gives no figure. Every difference is kept in the transcript."""
    others = [f"2021-{i:02d}" for i in range(1, 13) if i != 10]
    missing = [m for m in others if m not in months]
    if missing:
        raise TranscriptError(f"October 2021: other months missing {missing}")
    keys = {key_of(a["outfall"]) for a in annual["rows"]}
    stray = sorted({r["outfall"] for m in others for r in months[m]["rows"] if key_of(r["outfall"]) not in keys})
    if stray:
        raise TranscriptError(f"October 2021: monthly outfalls not on the annual sheet {stray}")
    diffs = []
    for a in annual["rows"]:
        k = key_of(a["outfall"])
        ev = sum(r["events"] for m in others for r in months[m]["rows"] if key_of(r["outfall"]) == k)
        gal = sum(r["volume_gal"] for m in others for r in months[m]["rows"] if key_of(r["outfall"]) == k)
        diffs.append({"outfall": a["outfall"], "watershed": a["watershed"], "events": a["events"] - ev,
                      "volume_gal": a["volume_gal"] - gal, "hours": None, "annual_events": a["events"],
                      "annual_volume_gal": a["volume_gal"], "other_months_events": ev, "other_months_volume_gal": gal})
    sheet = annual["monthly_volume_gal"]
    revisions = {m: sheet[m] - months[m]["total_row"]["volume_gal"] for m in others
                 if abs(sheet[m] - months[m]["total_row"]["volume_gal"]) > 1}       # 1 gallon: the reports' rounding
    placed = {}
    for m, amount in sorted(revisions.items()):
        hit = [d for d in diffs if d["volume_gal"] == amount and amount > 0]
        if len(hit) == 1:
            placed[m] = hit[0]["outfall"]
    unplaced = sum(v for m, v in revisions.items() if m not in placed)
    rest = sum(d["volume_gal"] for d in diffs) - sum(revisions[m] for m in placed) - unplaced
    if abs(rest - sheet[COMPUTED_MONTH]) > 1:
        raise TranscriptError(f"October 2021: the differences less the revisions ({rest:,}) do not give the sheet's "
                              f"October line ({sheet[COMPUTED_MONTH]:,})")
    rows, skipped = [], []
    for d in diffs:
        rev = next((m for m, o in placed.items() if o == d["outfall"]), None)
        if d["events"] == 0 and d["volume_gal"] == 0:
            continue                                                      # nothing left for October: a zero row
        why = (f"the difference is the annual sheet's revision of {rev} (its month line exceeds that report's Total "
               f"row by exactly these gallons)" if rev else
               "the difference is negative (the reports' 1-gallon rounding)" if d["volume_gal"] < 0 else
               f"the difference is not more than the {unplaced:,} gallons of revisions the sheet does not place"
               if d["volume_gal"] <= unplaced else
               "an event count of zero or less is left" if d["events"] <= 0 else None)
        if why:
            skipped.append({**d, "why": why})
            continue
        rows.append({**d, "figures_published": unplaced == 0})
    return {"computed": True, "rows": rows, "not_published": skipped,
            "method": {"volume": COMPUTED_VOLUME_METHOD, "events": COMPUTED_EVENTS_METHOD,
                       "withheld": None if unplaced == 0 else (
                           f"The annual sheet's figures for {_names(revisions)} 2021 are higher than those months' "
                           f"reports by {sum(revisions.values()):,} gallons, and {unplaced:,} gallons of that cannot "
                           f"be placed at an outfall. We show only outfalls whose difference is larger than that, "
                           f"without a count or gallons.")},
            "inputs": {"annual_sheet": annual["file"]["url"],
                       "monthly_reports": [months[m]["file"]["url"] for m in others]},
            "revisions": {m: {"gallons": v, "outfall": placed.get(m)} for m, v in sorted(revisions.items())},
            "unplaced_gal": unplaced,
            "check": {"differences_volume_gal": sum(d["volume_gal"] for d in diffs),
                      "less_revisions_volume_gal": rest,
                      "annual_sheet_october_volume_gal": sheet[COMPUTED_MONTH],
                      "differences_events": sum(d["events"] for d in diffs)}}


def extract(raw_dir: Path, out: Path = REFERENCE) -> dict:
    """Read the PDFs and the 2023 page reading in raw_dir; write the transcript. Raises TranscriptError."""
    raw_dir = Path(raw_dir)
    idx = read_index(raw_dir)
    months, annual = {}, {}
    for p in sorted(raw_dir.glob("*.pdf")):
        ym = month_of_file(p.name)
        am = re.match(r"^CSO-Overflow-Volumes-(20\d\d)\.pdf$", p.name)
        if ym:
            m = parse_month(pdf_text(p), ym)
            m["check"] = check_month(m["rows"], m["total_row"], KNOWN_DIFFERENCES.get(ym), where=ym)
            if ym in KNOWN_DIFFERENCES:
                m["known_difference"] = KNOWN_DIFFERENCES[ym]
            months[ym] = {"file": file_entry(p, idx), **m}
        elif am:
            annual[am.group(1)] = {"file": file_entry(p, idx), **parse_annual(pdf_text(p), am.group(1))}
    site = json.loads((raw_dir / "site-read-2023-01-to-04.json").read_text())
    for ym, m in sorted(site["months"].items()):
        rows = [{"outfall": r["outfall"], "watershed": r.get("discharge_to"), "events": int(r["events"]),
                 "volume_gal": int(r["volume_gal"]), "hours": r.get("hours")} for r in m["rows"]]
        entry = {"file": {"name": m["file"], "url": m["url"], "sha256": m["sha256"], "bytes": m["bytes"],
                          "read_at": site["read_at"],
                          "how": ("read from the commission's archive page on " + site["read_at"] +
                                  " (the Internet Archive holds no copy); the text was extracted in the browser")},
                 "rows": rows, "total_row": m["total_row"], "duration_label": "Hours"}
        entry["check"] = check_month(rows, m["total_row"], KNOWN_DIFFERENCES.get(ym), where=ym)
        if ym in KNOWN_DIFFERENCES:
            entry["known_difference"] = KNOWN_DIFFERENCES[ym]
        months[ym] = entry
    if COMPUTED_MONTH in months:
        raise TranscriptError("October 2021 has a report: it should not be computed")
    if "2021" not in annual:
        raise TranscriptError("no 2021 annual sheet")
    months[COMPUTED_MONTH] = compute_october(months, annual["2021"])
    expected = [f"{y}-{mo:02d}" for y in range(2019, 2024) for mo in range(1, 13) if f"{y}-{mo:02d}" <= "2023-04"]
    gaps = [m for m in expected if m not in months]
    if gaps:
        raise TranscriptError(f"months missing: {gaps}")
    watersheds = {}
    for y in sorted(annual):
        for r in annual[y]["rows"]:
            watersheds.setdefault(key_of(r["outfall"]), r["watershed"])
    for m in months.values():
        for r in m["rows"]:
            if r.get("watershed"):
                watersheds.setdefault(key_of(r["outfall"]), r["watershed"])
    doc = {"what": ("Springfield Water and Sewer Commission (NPDES MA0101613) monthly CSO reports, January 2019 to "
                    "April 2023, and its annual sheets 2019 to 2022, transcribed from the PDFs on its CSO Data Archive "
                    "page. Rain-gauge columns not transcribed. October 2021 has no report online and is computed "
                    "from the 2021 annual sheet and the other eleven months."),
           "page": PAGE_URL, "permit": PERMIT, "footnote": FOOTNOTE,
           "built_by": "python -m ingest.ma_springfield_archive --extract RAW_DIR (pypdf text extraction)",
           "hand_corrections": HANDCORRECTIONS, "watersheds": dict(sorted(watersheds.items())),
           "months": dict(sorted(months.items())), "annual": dict(sorted(annual.items()))}
    validate(doc)
    write_json(out, doc)
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--extract", metavar="RAW_DIR", help="rebuild the transcript from the PDFs in RAW_DIR")
    ap.add_argument("--out", help="events file to write (default data/build/events/ma-springfield-archive.json)")
    a = ap.parse_args(argv)
    if a.extract:
        doc = extract(Path(a.extract))
        print(f"{SOURCE_ID}: transcript of {len(doc['months'])} months -> {REFERENCE}")
        return 0
    return run(out=Path(a.out) if a.out else None)


if __name__ == "__main__":
    sys.exit(main())
