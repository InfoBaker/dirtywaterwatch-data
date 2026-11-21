"""Monthly CSO figures per outfall from EPA's per-state discharge monitoring report files: Ohio, Kentucky, Illinois,
Tennessee, Kansas, Georgia and Massachusetts (registry: oh-echo-dmr-cso, ky-echo-dmr-cso, il-echo-dmr-cso,
tn-echo-dmr-cso, ks-echo-dmr-cso, ga-echo-dmr-cso, ma-echo-dmr-cso-files) -> data/build/events/<source id>.json.

Source
  EPA ECHO's "Permit limit and DMR by jurisdiction" files (decision 45; docs/analysis/2026-11-17-echo-downloads.md, C1),
  https://echo.epa.gov/files/echodownloads/NPDES_by_state_year/<ST>_FY<yyyy>_NPDES_DMRS_LIMITS.zip, no key: one ZIP per
  state and federal fiscal year (October to September), holding <ST>_FY<yyyy>_NPDES_DMRS.csv (every value of every
  discharge monitoring report the state's permittees filed) and the permit limits. EPA refreshes the current and the
  previous year weekly (the ICIS-NPDES extract) and older years monthly; the current year's file is published some
  weeks after the year starts (FY2027's answered 404 on 2026-11-21). Read with the pipeline's named client from EPA's
  download server (echo.epa.gov/files), not the effluent-chart service (echodata.epa.gov) the Indiana, West Virginia,
  New Jersey and Massachusetts readers ask per permit, which did not answer from about 00:50Z to 03:40Z on 2026-11-19.
  Fields read: EXTERNAL_PERMIT_NMBR, PERM_FEATURE_NMBR, PERM_FEATURE_TYPE_CODE, PARAMETER_CODE, PARAMETER_DESC,
  MONITORING_LOCATION_CODE, NMBR_OF_REPORT, STATISTICAL_BASE_CODE, MONITORING_PERIOD_END_DATE, DMR_VALUE_ID,
  DMR_VALUE_NMBR, DMR_UNIT_DESC, LIMIT_UNIT_DESC, VALUE_RECEIVED_DATE, DAYS_LATE, NODI_CODE, VERSION_NMBR,
  LIMIT_SET_SCHEDULE_ID. The files name permits and plants, never a person.

What is read (STATES)
  Per state, the permits with at least one open combined sewer outfall in the outfall registry (common.
  load_outfall_registry; in_echo_cso_monthly.registry_outfalls and permits_to_read), less a state's permits another
  reader already takes from EPA (Massachusetts: Springfield, Holyoke and Chicopee, ingest/echo_cso_dmr_monthly.py).
  Only lines at an external outfall the registry holds as a combined sewer outfall of the permit, at the effluent-gross
  monitoring locations (codes 1 'Effluent Gross' and Y 'Effluent Gross (Supplementary)'), with a one-month monitoring
  period, and for the parameters that count or measure an overflow (codes per figure, in order of preference):
    events  74062 'Overflows', 84165 'Discharge event observation', 51484 'Number of Events'
    hours   50037 'Duration', 81381 and 82517 'Duration of discharge'
    volume  74063 'Overflow volume', 82220 'Flow, total'
  An outfall that files two codes for one figure keeps the first (the others counted in meta). Lines at a permit's
  other outfalls (Ohio's station 300, a plant's own outfall) and figures per year or quarter (Ohio's 51709 'Overflows'
  in occurrences a year, filed once in December) are counted in meta and not read.

Statistical bases (fold_rows)
  One DMR can carry a figure under several statistical bases. A monthly or period total (MO TOTAL, TOTAL; EVNT TOT for
  a count) is the month's figure. Ohio files each CSO figure under both the daily maximum and the monthly average
  columns: where the two agree (99 percent of Ohio's counts; checked against Columbus's own overflow table, 2026-11-21)
  the figure is the month's; where they differ, or a line gives only a statistic (a monthly average, a maximum), a rate
  (MGD, gal/d), a yes-or-no observation (N=0;Y=1) or a count above MAX_EVENTS_PER_MONTH, the figure is not the month's
  total: above zero it marks the month as a discharge month and gives no count, hours or volume, and the record writes
  it out as filed (row FiguredAs; in_echo_cso_monthly.figures). A unit missing from the value is the permit limit's
  unit on the same line (raw.dmr UnitFrom "limit").

Records (in_echo_cso_monthly.finish, the same as Indiana's)
  One per permit + outfall + month in which any figure is above zero: event_type cso, status ended, started_at the first
  and ended_at the last day of the month, time_precision month, reported_at the DMR's VALUE_RECEIVED_DATE (the day EPA
  received it), volume_gal from million gallons (a month's total only), the figures in volume_text, raw.dmr per figure
  (DMR value id, value, unit, statistical bases, NODI code, receipt date, version, parameter): permit, outfall, month,
  parameter and value cite EPA's DMR record. These are monthly figures, not events: the status build gives them the
  monthly mark and never red or yellow (build/status.py EPA_MONTHLY_SOURCES), and the charts never add them to the
  discharge counts. A month filed NODI C ('No Discharge') or zero for every figure the outfall carries is no record and
  clears an older monthly mark (meta.latest_month_by_outfall). Revisions: the higher VERSION_NMBR, then the later
  receipt, wins; a month the file no longer lists is kept and marked; the evidence store keeps every month read. The
  point and the water come from the registry row (a plant's point is never used); points rounded to three decimals.
  meta.outfalls_without_water lists the outfalls with records whose registry row has no water record.

Cache, budget and cadence
  data/build/<source id>-cache.json keeps, per fiscal year, the file's Last-Modified and size, the registry outfalls it
  was filtered on and the folded rows of the outfalls read; and the evidence store (in_echo_cso_monthly.merge_previous).
  Each run asks each file's headers (HEAD) and downloads only a file that changed (or whose registry outfalls changed),
  at most MAX_DOWNLOAD_BYTES a run and none after WALL_S seconds (the rest from the cache: meta.not_asked_this_run).
  The fiscal years read are those from --since (default 2025-01-01) to today. --backfill lifts the budget.

Failures
  A file that answers an error (after three tries) is failed: that state's run is ok=False, its cached rows of that year
  still used and the previous records kept. The current fiscal year's file answering 404 within CURRENT_FY_GRACE_DAYS of
  the year's start is "not published yet", no failure; any other 404 is a failure. A ZIP with no DMR table, or a table
  missing a field read, is a failed read. Each state is written on its own, so one state's failure leaves the others.

Run from pipeline/:  python -m ingest.echo_dmr_cso_states [--state OH] [--since 2025-01-01] [--backfill]
                     python -m ingest.echo_dmr_cso_states --state OH --file OH_FY2026_NPDES_DMRS_LIMITS.zip --fy 2026
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import requests

import common
import zones
from common import BUILD_DIR, HEADERS, RAW_DIR, read_json, save_raw, write_events, write_json
from ingest import in_echo_cso_monthly as M

BASE_URL = "https://echo.epa.gov/files/echodownloads/NPDES_by_state_year/"
DEFAULT_SINCE = "2025-01-01"
REQUEST_TIMEOUT = (15, 120)
MAX_DOWNLOAD_BYTES = 300_000_000       # a run downloads at most this much; the rest waits (the weekly refresh is ~165 MB)
WALL_S = 360                           # no download starts after this many seconds (the refresh caps a feed at 600 s)
CURRENT_FY_GRACE_DAYS = 120            # the current year's file answering 404 this soon after October 1 is not yet out
MAX_EVENTS_PER_MONTH = 744             # a count above one an hour of a 31-day month is kept as filed, not counted
FIGURES = {"events": ("74062", "84165", "51484"), "hours": ("50037", "81381", "82517"), "volume": ("74063", "82220")}
CODES = {c: name for name, cs in FIGURES.items() for c in cs}
LOCATIONS = {"1": "Effluent Gross", "Y": "Effluent Gross (Supplementary)"}
# statistical bases (ECHO's REF_STATISTICAL_BASE.csv, read 2026-11-21): short form as the effluent-chart service gives it
BASES = {"MP": "MO TOTAL", "TB": "TOTAL", "ET": "EVNT TOT", "DD": "DAILY MX", "MK": "MO AVG", "DB": "DAILY AV",
         "DC": "DAILY MN", "AF": "AVERAGE", "MB": "MAXIMUM", "ME": "MINIMUM", "AB": "ANNL AVG", "M6": "MAXIMUM"}
BASE_WORDS = {"MP": "a monthly total", "TB": "a total", "ET": "an event total", "DD": "a daily maximum",
              "MK": "a monthly average", "DB": "a daily average", "DC": "a daily minimum", "AF": "an average",
              "MB": "a maximum", "ME": "a minimum", "AB": "an annual average", "M6": "a maximum"}
TOTAL_BASES = {"MP", "TB"}
FIGURE_WORDS = {"events": "overflow count", "hours": "hours of discharge", "volume": "overflow volume"}
HOUR_UNITS = {"hr", "hr/mo", "hrs", "hours"}
NODI_WORDS = {"C": "No Discharge"}
FIELDS = ("EXTERNAL_PERMIT_NMBR", "PERM_FEATURE_NMBR", "PERM_FEATURE_TYPE_CODE", "PARAMETER_CODE", "PARAMETER_DESC",
          "MONITORING_LOCATION_CODE", "NMBR_OF_REPORT", "STATISTICAL_BASE_CODE", "MONITORING_PERIOD_END_DATE",
          "DMR_VALUE_ID", "DMR_VALUE_NMBR", "DMR_UNIT_DESC", "LIMIT_UNIT_DESC", "VALUE_RECEIVED_DATE", "DAYS_LATE",
          "NODI_CODE", "VERSION_NMBR", "LIMIT_SET_SCHEDULE_ID")
# a folded row in the cache: these effluent-chart field names, in this order
ROW_KEYS = ("permit", "feature", "ParameterCode", "ParameterDesc", "MonitoringLocationDesc", "MonitoringPeriodEndDate",
            "DMRValueId", "DMRValueNmbr", "DMRUnitDesc", "UnitFrom", "StatisticalBaseDesc", "StatisticalBases",
            "FiguredAs", "NODICode", "NODIDesc", "ValueReceivedDate", "DaysLate", "VersionNmbr", "LimitSetScheduleId")

AUTHORITY = ("EPA ECHO discharge monitoring reports (the operator's own monthly combined sewer overflow figures, filed "
             "with {agency}; reported weeks after the month)")
STATES = {
    "OH": {"source_id": "oh-echo-dmr-cso", "agency": "Ohio EPA"},
    "KY": {"source_id": "ky-echo-dmr-cso", "agency": "the Kentucky Division of Water"},
    "IL": {"source_id": "il-echo-dmr-cso", "agency": "Illinois EPA"},
    "TN": {"source_id": "tn-echo-dmr-cso", "agency": "the Tennessee Department of Environment and Conservation"},
    "KS": {"source_id": "ks-echo-dmr-cso", "agency": "the Kansas Department of Health and Environment"},
    "GA": {"source_id": "ga-echo-dmr-cso", "agency": "Georgia's Environmental Protection Division"},
    # Springfield, Holyoke and Chicopee are read by ingest/echo_cso_dmr_monthly.py (echo-cso-dmr-monthly)
    # Region 1's CSO permits put the CSO lines at the 'Storm Water' monitoring location (SW) as well as at 1
    "MA": {"source_id": "ma-echo-dmr-cso-files", "agency": "EPA Region 1 and MassDEP",
           "exclude": ("MA0101613", "MA0101630", "MA0101508"), "locations": {"SW": "Storm Water"}},
}


def fiscal_year(d: date) -> int:
    return d.year + 1 if d.month >= 10 else d.year


def fiscal_years(since: date, today: date) -> list[int]:
    return list(range(fiscal_year(since), fiscal_year(today) + 1))


def file_url(state: str, fy: int) -> str:
    return f"{BASE_URL}{state}_FY{fy}_NPDES_DMRS_LIMITS.zip"


def ddmon(mdy: str | None) -> str | None:
    """'05/31/2026' -> '31-MAY-26', the effluent-chart service's form, which in_echo_cso_monthly reads."""
    try:
        return datetime.strptime(mdy, "%m/%d/%Y").strftime("%d-%b-%y").upper() if mdy else None
    except ValueError:
        return None


def _num(v) -> float | None:
    return M.num(v)


def _unit_words(unit: str) -> str:
    return {"Mgal": "million gallons", "Mgal/mo": "million gallons"}.get(unit, unit)


def _fmt(v: float) -> str:
    return f"{v:g}"


def _unit_txt(name: str, unit: str) -> str:
    if name == "events" or not unit or (name == "hours" and unit in HOUR_UNITS):
        return ""
    return f" {_unit_words(unit)}"


def figured_as(name: str, unit: str, kept: list[tuple[str, float]]) -> str:
    """The filed form of a figure that is not the month's own total, for the record's text ('overflow volume filed
    as a daily maximum of 0.5 million gallons and a monthly average of 0.33 million gallons')."""
    vals = " and ".join(f"{BASE_WORDS.get(b, 'a figure (' + b + ')')} of {_fmt(v)}{_unit_txt(name, unit)}"
                        for b, v in kept)
    return f"{FIGURE_WORDS[name]} filed as {vals}"


def fold_rows(rows: list[dict], name: str, stats: Counter, locations: dict[str, str] | None = None) -> dict | None:
    """One row per permit, outfall, parameter, month, version and receipt from the lines EPA's file gives it (one per
    statistical base and value type): the effluent-chart row in_echo_cso_monthly reads, or None when no line says
    anything. Module docstring, 'Statistical bases'."""
    first = rows[0]
    unit_dmr = next((r["DMR_UNIT_DESC"] for r in rows if r["DMR_UNIT_DESC"]), "")
    unit_lim = next((r["LIMIT_UNIT_DESC"] for r in rows if r["LIMIT_UNIT_DESC"]), "")
    unit = unit_dmr or unit_lim or "(unit not given)"
    totals = [r for r in rows if r["STATISTICAL_BASE_CODE"] in TOTAL_BASES
              or (r["STATISTICAL_BASE_CODE"] == "ET" and name == "events")]
    cand = totals or rows
    said = [(r["STATISTICAL_BASE_CODE"], 0.0 if r["NODI_CODE"].upper() == "C" else _num(r["DMR_VALUE_NMBR"]), r)
            for r in cand if r["NODI_CODE"].upper() == "C" or (_num(r["DMR_VALUE_NMBR"]) is not None
                                                              and not r["NODI_CODE"])]
    bases = "; ".join(f"{BASES.get(r['STATISTICAL_BASE_CODE'], r['STATISTICAL_BASE_CODE'])} "
                      f"{r['DMR_VALUE_NMBR'] or ('NODI ' + r['NODI_CODE'] if r['NODI_CODE'] else 'blank')}"
                      for r in sorted(rows, key=lambda x: x["STATISTICAL_BASE_CODE"]))
    row = {"permit": first["EXTERNAL_PERMIT_NMBR"].strip().upper(), "feature": first["PERM_FEATURE_NMBR"].strip().upper(),
           "ParameterCode": first["PARAMETER_CODE"], "ParameterDesc": first["PARAMETER_DESC"],
           "MonitoringLocationDesc": (locations or LOCATIONS)[first["MONITORING_LOCATION_CODE"]],
           "MonitoringPeriodEndDate": ddmon(first["MONITORING_PERIOD_END_DATE"]),
           "DMRUnitDesc": unit, "UnitFrom": None if unit_dmr else ("limit" if unit_lim else None),
           "StatisticalBases": bases, "FiguredAs": None, "NODIDesc": None,
           "ValueReceivedDate": ddmon(first["VALUE_RECEIVED_DATE"]), "DaysLate": first["DAYS_LATE"] or None,
           "VersionNmbr": first["VERSION_NMBR"] or "0", "LimitSetScheduleId": first["LIMIT_SET_SCHEDULE_ID"] or None}
    if not said:
        # no value and no NODI C: another NODI code (says nothing) or a blank line
        code = next((r["NODI_CODE"] for r in cand if r["NODI_CODE"]), "")
        if not code:
            return None
        row.update(DMRValueId=cand[0]["DMR_VALUE_ID"], DMRValueNmbr=None, NODICode=code,
                   StatisticalBaseDesc=BASES.get(cand[0]["STATISTICAL_BASE_CODE"], cand[0]["STATISTICAL_BASE_CODE"]))
        return row
    values = sorted({v for _, v, _ in said})
    positive = [v for v in values if v > 0]
    if not positive:
        # zero and NODI C alike: no discharge
        r0 = said[0][2]
        nodi_c = all(r["NODI_CODE"].upper() == "C" for _, _, r in said)
        row.update(DMRValueId=r0["DMR_VALUE_ID"], DMRValueNmbr=None if nodi_c else "0",
                   NODICode="C" if nodi_c else None, NODIDesc=NODI_WORDS["C"] if nodi_c else None,
                   StatisticalBaseDesc=" and ".join(sorted({BASES.get(b, b) for b, _, _ in said})))
        return row
    top = max(said, key=lambda x: (x[1] or 0))
    row.update(DMRValueId=top[2]["DMR_VALUE_ID"], DMRValueNmbr=top[2]["DMR_VALUE_NMBR"], NODICode=None,
               StatisticalBaseDesc=" and ".join(sorted({BASES.get(b, b) for b, _, _ in said})))
    kept = sorted({(b, v) for b, v, _ in said}, key=lambda x: (["DD", "MK"].index(x[0]) if x[0] in ("DD", "MK") else 2,
                                                                x[0], x[1]))
    if not totals and {b for b, _, _ in said} >= {"DD", "MK"}:
        # Ohio's two columns: one figure in both is the month's (unless the report holds daily entries: mark_daily)
        row["_pair"] = "agree" if len(values) == 1 else "differ"
    if len(values) > 1:
        row["FiguredAs"] = figured_as(name, unit, kept)
        stats["figures_with_disagreeing_bases"] += 1
    elif not totals and len({b for b, _, _ in said}) < 2:
        # one statistic alone (a monthly average, a maximum): not the month's total
        row["FiguredAs"] = figured_as(name, unit, kept)
        stats["figures_given_only_as_a_statistic"] += 1
    elif unit == "N=0;Y=1":
        row["FiguredAs"] = "a discharge filed as observed (yes)"
        stats["figures_filed_yes_or_no"] += 1
    elif unit.endswith("/d") or unit in ("MGD", "gpd"):
        row["FiguredAs"] = f"{FIGURE_WORDS[name]} filed as a rate of {_fmt(positive[0])} {unit}"
        stats["figures_filed_as_a_rate"] += 1
    elif name == "events" and positive[0] > MAX_EVENTS_PER_MONTH:
        row["FiguredAs"] = f"overflow count filed as {_fmt(positive[0])}, more than one an hour of the month"
        stats["implausible_counts"] += 1
    elif name == "hours" and unit not in HOUR_UNITS:
        row["FiguredAs"] = f"duration filed as {_fmt(positive[0])} {unit}"
        stats["durations_in_other_units"] += 1
    return row


def mark_daily(rows: list[dict], stats: Counter) -> list[dict]:
    """A report (permit, outfall, month, version, receipt) in which one figure's daily maximum and monthly average
    differ holds daily entries; a figure whose two columns agree there is one day's figure, not the month's total."""
    daily = {(r["permit"], r["feature"], r["MonitoringPeriodEndDate"], r["VersionNmbr"], r["ValueReceivedDate"])
             for r in rows if r.get("_pair") == "differ"}
    for r in rows:
        k = (r["permit"], r["feature"], r["MonitoringPeriodEndDate"], r["VersionNmbr"], r["ValueReceivedDate"])
        if r.pop("_pair", None) == "agree" and k in daily and not r.get("FiguredAs") and (_num(r["DMRValueNmbr"]) or 0) > 0:
            name = CODES[r["ParameterCode"]]
            r["FiguredAs"] = (f"{FIGURE_WORDS[name]} filed as {_fmt(_num(r['DMRValueNmbr']))}"
                              f"{_unit_txt(name, r['DMRUnitDesc'])} for both the daily maximum and the monthly "
                              "average of daily entries")
            stats["figures_in_reports_of_daily_entries"] += 1
    for r in rows:
        r.pop("_pair", None)
    return rows


def _not_monthly_unit(unit: str) -> bool:
    return any(unit.endswith(s) for s in ("/yr", "/qtr", "/year", "/quarter"))


def parse_zip(path: Path, keys: set[tuple[str, str]], permits: set[str], stats: Counter,
              locations: dict[str, str] | None = None) -> list[dict]:
    """The folded rows of EPA's state file for the registry's combined sewer outfalls (keys) of the permits read, at
    the monitoring locations given (code -> description; LOCATIONS unless given)."""
    locations = locations or LOCATIONS
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.upper().endswith("_NPDES_DMRS.CSV")), None)
        if name is None:
            raise ValueError("no DMR table in the ZIP")
        groups: dict[tuple, list[dict]] = defaultdict(list)
        with z.open(name) as f:
            rd = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline=""))
            hdr = next(rd)
            missing = [k for k in FIELDS if k not in hdr]
            if missing:
                raise ValueError("DMR table without " + ", ".join(missing))
            ix = {k: hdr.index(k) for k in FIELDS}
            pc, pp = ix["PARAMETER_CODE"], ix["EXTERNAL_PERMIT_NMBR"]
            for line in rd:
                if len(line) < len(hdr) or line[pc] not in CODES or line[pp].strip().upper() not in permits:
                    continue
                r = {k: line[i].strip() for k, i in ix.items()}
                permit = r["EXTERNAL_PERMIT_NMBR"].upper()
                key = common.outfall_key(permit, r["PERM_FEATURE_NMBR"])
                if key not in keys:
                    stats[f"lines_at_outfalls_not_in_registry_as_cso:{permit}:{r['PERM_FEATURE_NMBR']}"] += 1
                    continue
                if r["PERM_FEATURE_TYPE_CODE"] != "EXO":
                    stats["lines_not_at_an_external_outfall"] += 1
                    continue
                if r["MONITORING_LOCATION_CODE"] not in locations:
                    stats[f"lines_at_other_monitoring_locations:{r['MONITORING_LOCATION_CODE']}"] += 1
                    continue
                if r["NMBR_OF_REPORT"] not in ("", "1"):
                    stats["lines_with_a_monitoring_period_longer_than_a_month"] += 1
                    continue
                if _not_monthly_unit(r["DMR_UNIT_DESC"] or r["LIMIT_UNIT_DESC"]):
                    stats["lines_in_units_per_year_or_quarter"] += 1
                    continue
                groups[(permit, r["PERM_FEATURE_NMBR"].upper(), r["PARAMETER_CODE"], r["MONITORING_PERIOD_END_DATE"],
                        r["VERSION_NMBR"], r["VALUE_RECEIVED_DATE"], r["LIMIT_SET_SCHEDULE_ID"])].append(r)
    out = []
    for k, rows in groups.items():
        row = fold_rows(rows, CODES[k[2]], stats, locations)
        if row is not None:
            out.append(row)
        else:
            stats["blank_lines"] += 1
    out = mark_daily(out, stats)
    out.sort(key=lambda r: (r["permit"], r["feature"], r["ParameterCode"], r["MonitoringPeriodEndDate"] or "",
                            r["VersionNmbr"]))
    return out


def preferred(rows: list[dict], stats: Counter) -> list[dict]:
    """An outfall that files two codes for one figure keeps the first code of FIGURES in any month read."""
    have: dict[tuple, set] = defaultdict(set)
    for r in rows:
        have[(r["permit"], r["feature"], CODES[r["ParameterCode"]])].add(r["ParameterCode"])
    keep = {k: next(c for c in FIGURES[k[2]] if c in cs) for k, cs in have.items()}
    out = []
    for r in rows:
        if keep[(r["permit"], r["feature"], CODES[r["ParameterCode"]])] == r["ParameterCode"]:
            out.append(r)
        else:
            stats[f"other_codes_for_the_same_figure:{r['permit']}:{r['feature']}:{r['ParameterCode']}"] += 1
    return out


def to_results(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """The folded rows as the effluent-chart answers in_echo_cso_monthly.collect reads, keyed (permit, code)."""
    res: dict[tuple[str, str], dict] = {}
    for r in rows:
        a = res.setdefault((r["permit"], r["ParameterCode"]), {"Message": "Success", "CWPName": None, "PermFeatures": []})
        feat = next((f for f in a["PermFeatures"] if f["PermFeatureNmbr"] == r["feature"]), None)
        if feat is None:
            feat = {"PermFeatureNmbr": r["feature"], "PermFeatureTypeDesc": "External Outfall", "Parameters": []}
            a["PermFeatures"].append(feat)
        par = next((p for p in feat["Parameters"] if p["MonitoringLocationDesc"] == r["MonitoringLocationDesc"]), None)
        if par is None:
            par = {"ParameterCode": r["ParameterCode"], "ParameterDesc": r["ParameterDesc"],
                   "MonitoringLocationDesc": r["MonitoringLocationDesc"], "DischargeMonitoringReports": []}
            feat["Parameters"].append(par)
        par["DischargeMonitoringReports"].append({k: v for k, v in r.items() if k not in ("permit", "feature")})
    return res


def pack(rows: list[dict]) -> list[list]:
    return [[r.get(k) for k in ROW_KEYS] for r in rows]


def unpack(rows: list[list]) -> list[dict]:
    return [dict(zip(ROW_KEYS, r)) for r in rows]


def registry_hash(keys: set[tuple[str, str]]) -> str:
    return hashlib.sha1(json.dumps(sorted(keys)).encode()).hexdigest()[:16]


def head(url: str) -> tuple[int | None, str | None, int | None, str]:
    """(status, Last-Modified, Content-Length, how) of a file, three tries; status None when nothing answered."""
    err = "not tried"
    for i in range(3):
        try:
            r = requests.head(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if r.status_code == 404:
                return 404, None, None, "HTTP 404"
            r.raise_for_status()
            n = r.headers.get("Content-Length")
            return r.status_code, r.headers.get("Last-Modified"), int(n) if n and n.isdigit() else None, "ok"
        except requests.RequestException as e:
            err = M.error_category(e)
            time.sleep(3 * (i + 1))
    return None, None, None, err


def download(url: str, dest: Path) -> str:
    """The file to dest; '' when done, else a bounded error category (never answer text)."""
    err = "not tried"
    for i in range(3):
        try:
            with requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True) as r:
                r.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if not zipfile.is_zipfile(dest):
                raise ValueError("not a ZIP")
            return ""
        except (requests.RequestException, ValueError, OSError) as e:
            err = M.error_category(e) if isinstance(e, requests.RequestException) else "not a ZIP"
            time.sleep(3 * (i + 1))
    return err


class Budget:
    def __init__(self, max_bytes: int | None, wall_s: float | None):
        self.left, self.until = max_bytes, (time.monotonic() + wall_s) if wall_s else None

    def allows(self, n: int | None) -> bool:
        if self.until is not None and time.monotonic() > self.until:
            return False
        return self.left is None or (n or 0) <= self.left

    def spend(self, n: int | None) -> None:
        if self.left is not None:
            self.left -= n or 0


def cache_file(source_id: str) -> Path:
    return BUILD_DIR / f"{source_id}-cache.json"


def locations_of(state: str) -> dict[str, str]:
    return {**LOCATIONS, **(STATES[state].get("locations") or {})}


def read_state_files(state: str, keys: set, permits: set, since: date, today: date, cache: dict, budget: Budget,
                     stats: Counter, local: dict[int, Path] | None = None) -> tuple[list[dict], dict, dict]:
    """(folded rows of every fiscal year read, fetch log by year, file facts by year); cache['files'] updated."""
    files = cache.setdefault("files", {})
    rows, log, facts = [], {}, {}
    rh = registry_hash(keys | {("locations", ",".join(sorted(locations_of(state))))})
    sid = STATES[state]["source_id"]
    for fy in fiscal_years(since, today):
        k, url = f"FY{fy}", file_url(state, fy)
        old = files.get(k) or {}
        if local and fy not in local:
            # a --file run reads only its file: the other years from the cache, nothing asked of EPA
            if old.get("rows") is not None:
                rows += unpack(old["rows"])
                stats.update(old.get("stats") or {})
                log[k] = f"cache (file of {old.get('last_modified')}; not read: a --file run)"
            else:
                log[k] = "not asked this run (a --file run); no earlier read"
            continue
        if local and fy in local:
            st, lm, n, how = 200, f"local file {local[fy].name}", local[fy].stat().st_size, "ok"
        else:
            st, lm, n, how = head(url)
        if st == 404:
            fy_start = date(fy - 1, 10, 1)
            if fy == fiscal_year(today) and (today - fy_start).days <= CURRENT_FY_GRACE_DAYS:
                log[k] = "not published yet (HTTP 404)"
            else:
                log[k] = "failed (HTTP 404)"
            if old.get("rows"):
                rows += unpack(old["rows"])
                stats.update(old.get("stats") or {})
            continue
        if st is None:
            log[k] = f"failed ({how})"
            if old.get("rows"):
                rows += unpack(old["rows"])
                stats.update(old.get("stats") or {})
                log[k] += f"; cached rows of the file of {old.get('last_modified')} used"
            continue
        if old.get("rows") is not None and old.get("last_modified") == lm and old.get("length") == n \
                and old.get("registry") == rh and not (local and fy in local):
            rows += unpack(old["rows"])
            stats.update(old.get("stats") or {})
            log[k] = f"cache (file of {lm}, read {old.get('read_at')})"
            facts[k] = {"url": url, "last_modified": lm, "length": n, "rows": len(old["rows"])}
            continue
        if not (local and fy in local) and not budget.allows(n):
            if old.get("rows") is not None:
                rows += unpack(old["rows"])
                stats.update(old.get("stats") or {})
                log[k] = f"stale cache (file of {old.get('last_modified')}; not read this run: download budget)"
            else:
                log[k] = "not asked this run (download budget); no earlier read"
            continue
        path = local[fy] if local and fy in local else RAW_DIR / sid / f"{state}_FY{fy}.zip"
        if not (local and fy in local):
            budget.spend(n)
            err = download(url, path)
            if err:
                log[k] = f"failed ({err})"
                if old.get("rows"):
                    rows += unpack(old["rows"])
                    stats.update(old.get("stats") or {})
                continue
        file_stats: Counter = Counter()
        try:
            got = parse_zip(path, keys, permits, file_stats, locations_of(state))
        except (ValueError, zipfile.BadZipFile, OSError) as e:
            log[k] = f"failed (unreadable file: {e if isinstance(e, ValueError) else type(e).__name__})"
            if old.get("rows"):
                rows += unpack(old["rows"])
                stats.update(old.get("stats") or {})
            continue
        finally:
            if not (local and fy in local):
                path.unlink(missing_ok=True)       # 10 to 60 MB; the folded rows are kept (save_raw and the cache)
        save_raw(sid, json.dumps({"url": url, "last_modified": lm, "rows": pack(got)}).encode(), f"FY{fy}.json")
        files[k] = {"url": url, "last_modified": lm, "length": n, "registry": rh,
                    "read_at": datetime.now(UTC).replace(microsecond=0).isoformat(), "stats": dict(file_stats),
                    "rows": pack(got)}
        stats.update(file_stats)
        rows += got
        log[k] = f"live (file of {lm})"
        facts[k] = {"url": url, "last_modified": lm, "length": n, "rows": len(got)}
    return rows, log, facts


def zone_for(state: str):
    return lambda o, lat, lon: zones.zone_for(state, lat, lon) or zones.STATE_ZONES.get(state)


def run_state(state: str, since: date, today: date, budget: Budget, registry_rows: list[dict],
              local: dict[int, Path] | None = None) -> int:
    cfg = STATES[state]
    sid = cfg["source_id"]
    reg = M.registry_outfalls(registry_rows, state)
    permits = [p for p in M.permits_to_read(reg) if p not in set(cfg.get("exclude") or ())]
    keys = {k for k in reg if k[0] in set(permits)}
    path = cache_file(sid)
    doc = read_json(path, {}) or {}
    cache = {"files": doc.get("files") or {}}
    stats: Counter = Counter()
    rows, log, facts = read_state_files(state, keys, set(permits), since, today, cache, budget, stats, local)
    rows = preferred(rows, stats)
    evidence_store = doc.get("evidence") or {}

    def save_store(store: dict) -> None:
        write_json(path, {"source_id": sid, "about": "per fiscal year: EPA's file facts and the folded DMR rows of the "
                          "registry's combined sewer outfalls (ingest/echo_dmr_cso_states.py); 'evidence' keeps the "
                          "winning DMR row of every outfall, month and parameter ever read (in_echo_cso_monthly."
                          "merge_previous)", "files": cache["files"], "evidence": dict(sorted(store.items()))})
    save_store(evidence_store)
    if not any(v.startswith(("live", "cache", "stale")) for v in log.values()):
        # nothing read this run and nothing cached: never written as a healthy feed with no records
        err = "no file read: " + "; ".join(f"{k} {v}" for k, v in log.items())
        write_events(sid, [], ok=False, error=err)
        print(f"{sid}: {err}", file=sys.stderr)
        return 1
    feed = {"source_id": sid, "params": {c: n for c, n in CODES.items()},
            "authority": AUTHORITY.format(agency=cfg["agency"]), "zone": zone_for(state),
            "source_url": lambda permit: f"https://echo.epa.gov/effluent-charts#{permit}",
            "location_ok": lambda desc, ok=frozenset(locations_of(state).values()): desc in ok,
            "cadence": ("EPA's state file per fiscal year, read when its Last-Modified changes (weekly for the current "
                        "and previous year); DMRs reach EPA weeks after the month"),
            "note": ("the operator's monthly DMR figures for this outfall, not an individual discharge: no day is "
                     "given")}
    lines = Counter()
    skipped = {}
    for k, v in stats.items():
        head_, _, rest = k.partition(":")
        if rest:
            lines[head_] += v
            skipped.setdefault(head_, {})[rest] = v
    meta_extra = {"state": state, "files": facts, "file_log": log,
                  **{k: v for k, v in stats.items() if ":" not in k},
                  **{f"{k}_total": v for k, v in lines.items()}, "skipped_lines": skipped,
                  "codes": FIGURES, "monitoring_locations_read": locations_of(state),
                  **({"permits_read_by_another_feed": list(cfg["exclude"])} if cfg.get("exclude") else {})}
    rc = M.finish(to_results(rows), reg, M.dischargers(state), since=since.isoformat(), permits=permits,
                  fetch_log=log, evidence_store=evidence_store, save_store=save_store, feed=feed,
                  meta_extra=meta_extra)
    annotate(sid, reg)
    return rc


def annotate(source_id: str, reg: dict) -> None:
    """meta.outfalls_without_water: the outfalls with records whose registry row has no water record."""
    p = common.EVENTS_DIR / f"{source_id}.json"
    doc = read_json(p, {}) or {}
    recs = doc.get("records") or []
    if not doc:
        return
    seen = {}
    for r in recs:
        o = reg.get(common.outfall_key(r.get("npdes_permit"), r.get("outfall_id"))) or {}
        if not o.get("water_slug"):
            seen[f"{r.get('npdes_permit')}|{r.get('outfall_id')}"] = o.get("receiving_water_echo")
    meta = doc.setdefault("meta", {})
    outfalls = {f"{r.get('npdes_permit')}|{r.get('outfall_id')}" for r in recs}
    meta["outfalls_with_records"] = len(outfalls)
    meta["outfalls_without_water"] = dict(sorted(seen.items()))
    write_json(p, doc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", action="append", choices=sorted(STATES), help="one state (repeatable); default all")
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--backfill", action="store_true", help="no download budget (a first load or a history reread)")
    ap.add_argument("--file", type=Path, help="a saved state ZIP (with --state and --fy): read instead of EPA's")
    ap.add_argument("--fy", type=int, help="the fiscal year of --file")
    args = ap.parse_args(argv)
    if args.file and (not args.fy or not args.state or len(args.state) != 1):
        ap.error("--file needs --fy and one --state")
    since = date.fromisoformat(args.since)
    today = datetime.now(UTC).date()
    budget = Budget(None, None) if args.backfill else Budget(MAX_DOWNLOAD_BYTES, WALL_S)
    registry_rows = common.load_outfall_registry(provisional=False)
    rc = 0
    for st in args.state or list(STATES):
        local = {args.fy: args.file} if args.file else None
        try:
            rc = max(rc, run_state(st, since, today, budget, registry_rows, local))
        except Exception as e:  # one state's unexpected failure must not stop the others
            sid = STATES[st]["source_id"]
            write_events(sid, [], ok=False, error=f"{type(e).__name__} while reading {st}")
            print(f"{sid}: {type(e).__name__} while reading {st}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
