"""Monthly CSO figures per Indiana outfall from EPA ECHO Discharge Monitoring Reports (registry: in-echo-dmr-cso).

Source
  ECHO Effluent Charts REST service (also fed-echo-effluent-charts-rest),
  https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart?output=JSON&p_id=<permit>
  &parameter_code=<code>&start_date=MM/DD/YYYY&end_date=MM/DD/YYYY, no key. 327 IAC 5-2.1-7 has every Indiana CSO
  community document its overflows on a monthly CSO discharge monitoring report; IDEM's permits ask, per CSO outfall
  ('Effluent Gross'), three monthly totals (read 2026-11-14 on LaPorte, South Bend, Fort Wayne, Gary and Indianapolis):
    84165 'Discharge event observation [Visual Monitoring]'  MO TOTAL  #/mo   (the number of discharge events)
    50037 'Duration'                                          MO TOTAL  hr/mo  (hours of discharge)
    74063 'Overflow volume [SS0 volume, CSO volume]'          MO TOTAL  Mgal   (million gallons)
  A month with no overflow is filed NODI C ('No Discharge'). One request per permit and parameter, a short sleep
  between them; each answer is kept with common.save_raw (data/raw/in-echo-dmr-cso/<stamp>.<permit>-<code>.json, not
  read back) and, compacted to the fields the records read, in the run-to-run cache data/build/in-echo-dmr-cso-cache.json
  (data/build is kept between cloud runs; about 1 MB): a run reuses an answer fetched in the last CACHE_DAYS days with
  the same start date (--refresh asks again), so ECHO is asked about once a week per permit and parameter. A run asks
  at most MAX_LIVE_REQUESTS (the oldest answers first) and reads the rest from older answers (meta.not_asked_this_run),
  so a run stays within the refresh's per-feed time cap; 276 requests took about 15 minutes on 2026-11-14.

Permits
  Every Indiana permit with at least one open combined sewer outfall in the outfall registry (every data/outfalls-*.json
  through common.load_outfall_registry: IDEM's layer in data/outfalls-in.json, else EPA's inventory), 90 on 2026-11-14.

Records
  One per permit + outfall + month in which any of the three figures is above zero: event_type cso, status ended,
  started_at the first and ended_at the last day of the month, time_precision month, reported_at the DMR's
  ValueReceivedDate (the day EPA received it), volume_gal the month's million gallons times 1,000,000 when given,
  volume_text 'N discharge events, H hours, V million gallons in YYYY-MM (monthly DMR totals)'; a volume implying more
  than MAX_MGAL_PER_HOUR million gallons an hour of the month's hours stays in the text only (raw.volume_note). These are monthly
  totals, not events: the status build gives them the monthly mark and never red or yellow (time_precision month;
  build/status.py EPA_MONTHLY_SOURCES), and the charts never add them to the discharge counts. NODI C months and months
  with every figure zero are not records; they are counted in meta and kept per outfall in
  meta.latest_month_by_outfall (a newer month of no discharge clears an older monthly mark only when every
  parameter the outfall's DMRs carry, in any month any run has read, is a zero or NODI C that month; a
  no-discharge finding whose evidence later turns conflicting is withdrawn and recomputed: reconcile_latest).
  Other NODI codes and empty values say nothing. Only 'Effluent Gross' lines at external outfalls of the registry's
  CSO rows are read; a plant's own outfall and an internal monitoring point are counted in meta and skipped. raw.time_zone is the outfall's county's
  zone (zones.indiana_zone: the month is a calendar month on that clock); the point, receiving water and water record
  come from the registry row.

Revisions and history (Astra review 2026-11-14)
  Two rows for one outfall, parameter and month: the higher VersionNmbr, then the later receipt, wins (revision_key),
  never the larger value. Each run is reconciled with the previous file: a month the source no longer lists at all is
  kept with raw._missing_from_source_since; a month the source now files as no discharge on complete, conflict-free
  evidence (every parameter the outfall carries a zero or NODI C: no_discharge_confirmed) is withdrawn (counted in
  meta.months_withdrawn_by_the_source), and one that reads no discharge only in part or in conflict is kept with
  raw.no_discharge_unconfirmed (verification 3, 2026-11-15, P2-1). Equally ranked rows that disagree, one of them
  filing a discharge, make a discharge month in dispute whatever order they arrive in (raw.conflicts, the figures
  in conflict unknown, no volume counted); latest_month_by_outfall is recomputed from the evidence of every run
  (reconcile_latest), so an outfall this run did not read keeps its observation. An outfall whose registry point is
  the treatment plant's (coords_from facility) gets no point (raw.point_note); points are rounded to three decimals.
  raw.parameters gives the chart builder events and hours.

Lag and cadence
  DMRs are due on the 28th of the following month in Indiana and ECHO refreshes weekly, so a month appears four to eight
  weeks after it ends (the median lag is measured from ValueReceivedDate and kept in meta.median_days_month_end_to_receipt).
  The request covers --since (default 2025-01-01) to today, so late and revised DMRs are picked up.

Failures
  A permit ECHO calls invalid ('NPDES ID ... is invalid!': IN0020215 on 2026-11-14, a permit IDEM's layer lists that
  ICIS does not hold) is named in meta.fetch as 'not in ECHO' and is no failure. A permit whose requests fail three
  times is named in meta.fetch; the run is ok=False and the previous records stay
  (a first run with nothing to keep writes what it has, still ok=False). Each try waits at most REQUEST_TIMEOUT s; after
  MAX_CONSECUTIVE_FAILURES failed tries in a row the run asks nothing more.

Run from pipeline/:  python -m ingest.in_echo_cso_monthly [--since 2025-01-01] [--refresh]
"""
from __future__ import annotations

import argparse
import calendar
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime

import requests

import common
import zones
from common import BUILD_DIR, DATA_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "in-echo-dmr-cso"
URL = "https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart"
PARAMS = {"84165": "events", "50037": "hours", "74063": "volume"}
AUTHORITY = ("EPA ECHO discharge monitoring reports (the operator's own monthly CSO totals, filed with IDEM; "
             "reported weeks after the month)")
DEFAULT_SINCE = "2025-01-01"
SLEEP_S = 1.0
CACHE_DAYS = 7
MAX_LIVE_REQUESTS = 120        # a run asks at most this many; the rest wait for the next run (oldest first)
CACHE_FILE = BUILD_DIR / "in-echo-dmr-cso-cache.json"
REQUEST_TIMEOUT = 60
MAX_CONSECUTIVE_FAILURES = 5
# a filed volume implying more than this many million gallons an hour is kept as text only (one outfall-month on
# 2026-11-14: 28,482 'Mgal' in 15 hours, IN0024741 001, 2026-09; the largest plausible ones run 2 to 4 an hour)
MAX_MGAL_PER_HOUR = 100
MGAL = {"Mgal": 1_000_000, "MG": 1_000_000, "MG/mo": 1_000_000, "Mgal/mo": 1_000_000, "gal": 1, "gal/mo": 1}
RAW_FIELDS = ("DMRValueId", "DMRValueNmbr", "DMRUnitDesc", "StatisticalBaseDesc", "NODICode", "NODIDesc",
              "ValueReceivedDate", "DMRDueDate", "DaysLate", "VersionNmbr", "LimitSetScheduleId")
# Fields only EPA's per-state DMR files give a row (ingest/echo_dmr_cso_states.py fold_rows); kept in raw.dmr and in
# the evidence store when present, so Indiana's records and store are unchanged. FiguredAs marks a figure that is not
# the month's own total (the statistical bases disagree, a yes/no observation, an implausible count): it says whether
# there was a discharge, never how much (figures).
STATE_FILE_FIELDS = ("ParameterCode", "MonitoringLocationDesc", "StatisticalBases", "FiguredAs", "UnitFrom")


def registry_outfalls(rows: list[dict] | None = None, state: str = "IN") -> dict[tuple[str, str], dict]:
    """(permit, outfall key) -> the registry row of every combined sewer outfall of the state (open or closed)."""
    rows = common.load_outfall_registry(provisional=False) if rows is None else rows
    out = {}
    for r in rows:
        if r.get("state") != state or str(r.get("outfall_kind") or "cso") != "cso":
            continue
        out[common.outfall_key(r.get("npdes_permit"), r.get("outfall"))] = r
    return out


def permits_to_read(reg: dict) -> list[str]:
    """Permits with at least one open combined sewer outfall in the registry."""
    return sorted({p for (p, _), r in reg.items() if not str(r.get("outfall_status") or "").upper().startswith("CLS")})


def dischargers(state: str = "IN") -> dict[str, dict]:
    out = {}
    for d in read_json(DATA_DIR / "dischargers.json", []) or []:
        if d.get("state") != state:
            continue
        for p in d.get("npdes_permits") or [d.get("npdes_permit")]:
            if p:
                out.setdefault(p, d)
    return out


def compact(res: dict) -> dict:
    """The answer with only what the records read (the facility name, the start date and per outfall the three
    parameters' DMR rows with RAW_FIELDS): the run-to-run cache (CACHE_FILE) stays small."""
    feats = []
    for f in res.get("PermFeatures") or []:
        pars = [{"ParameterCode": par.get("ParameterCode"), "ParameterDesc": par.get("ParameterDesc"),
                 "MonitoringLocationDesc": par.get("MonitoringLocationDesc"),
                 "DischargeMonitoringReports": [{k: row.get(k) for k in ("MonitoringPeriodEndDate", *RAW_FIELDS)}
                                                for row in par.get("DischargeMonitoringReports") or []]}
                for par in f.get("Parameters") or [] if str(par.get("ParameterCode")) in PARAMS]
        if pars:
            feats.append({"PermFeatureNmbr": f.get("PermFeatureNmbr"), "PermFeatureTypeDesc": f.get("PermFeatureTypeDesc"),
                          "Parameters": pars})
    return {"Message": res.get("Message"), "CWPName": res.get("CWPName"), "StartDate": res.get("StartDate"),
            "PermFeatures": feats}


def load_cache() -> dict:
    doc = read_json(CACHE_FILE, {}) or {}
    return doc.get("answers") or {}


def cached(cache: dict, permit: str, code: str, since: date, today: date, stale_ok: bool = False):
    """(answer, how) from the cache: an answer fetched in the last CACHE_DAYS days for this permit, parameter and start
    date ('cache'); with stale_ok, an older one ('stale cache'); (None, None) when there is none."""
    e = cache.get(f"{permit}-{code}") or {}
    if e.get("since") != since.isoformat() or not e.get("fetched"):
        return None, None
    try:
        age = (today - date.fromisoformat(e["fetched"])).days
    except ValueError:
        return None, None
    if age <= CACHE_DAYS:
        return e, f"cache (fetched {e['fetched']})"
    if stale_ok:
        return e, f"stale cache (fetched {e['fetched']}; not asked this run: request budget)"
    return None, None


def fetch(permit: str, code: str, since: date) -> tuple[dict | None, str]:
    params = {"output": "JSON", "p_id": permit, "parameter_code": code,
              "start_date": since.strftime("%m/%d/%Y"), "end_date": date.today().strftime("%m/%d/%Y")}
    err = "not tried"
    for i in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            js = r.json()
            msg = str(((js.get("Results") or {}).get("Error") or {}).get("ErrorMessage") or "")
            if "is invalid" in msg:
                # an answer, not a failure: never retried; only ECHO's fixed wording is kept, never other answer text
                return None, f"not in ECHO (NPDES ID {permit} is invalid!)"
            if (js.get("Results") or {}).get("Message") != "Success":
                raise ValueError("answer not Success")
            # only what the records read is saved (the answer also carries the plant's street address)
            save_raw(SOURCE_ID, json.dumps({"Results": compact(js["Results"])}).encode(), f"{permit}-{code}.json")
            return js["Results"], "live"
        except (requests.RequestException, ValueError) as e:
            err = error_category(e)
            time.sleep(3 * (i + 1))
    return None, f"failed ({err})"


def error_category(e: Exception) -> str:
    """A bounded category for a failed request, never the answer's text or the exception's own message (which can
    quote the answer: re-review 2026-11-14 P1-2)."""
    if isinstance(e, requests.HTTPError):
        code = getattr(getattr(e, "response", None), "status_code", None)
        return f"HTTP {int(code)}" if isinstance(code, int) else "HTTP error"
    if isinstance(e, requests.Timeout):
        return "timeout"
    if isinstance(e, requests.ConnectionError):
        return "connection error"
    if isinstance(e, requests.RequestException):
        return "request error"
    if str(e) == "answer not Success":
        return "answer not Success"
    return "malformed answer"


def month_bounds(period_end: str) -> tuple[str, str, str]:
    d = datetime.strptime(period_end, "%d-%b-%y").date()
    first = d.replace(day=1)
    last = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    return first.isoformat(), last.isoformat(), first.strftime("%Y-%m")


def ddmon(s: str | None) -> str | None:
    try:
        return datetime.strptime(s, "%d-%b-%y").date().isoformat() if s else None
    except ValueError:
        return None


def num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def revision_key(row: dict) -> tuple:
    """The order of two DMR rows for one outfall, parameter and month: the higher VersionNmbr (a revised report), then
    the later ValueReceivedDate, then the row that says something (a value or a NODI code); never the larger value
    (Astra review 2026-11-14 P2-9: a correction downward or to NODI C must win)."""
    try:
        version = int(str(row.get("VersionNmbr") or "0").strip() or 0)
    except ValueError:
        version = 0
    received = ddmon(row.get("ValueReceivedDate")) or ""
    says = num(row.get("DMRValueNmbr")) is not None or bool(row.get("NODICode"))
    return version, received, says


def collect(results: dict[tuple[str, str], dict], reg: dict, stats: dict,
            params: dict[str, str] | None = None, location_ok=None) -> tuple[dict, dict]:
    """(permit, feature, month) -> {param: DMR row}; and permit -> ECHO facility name. results is keyed (permit, code).
    params: parameter code -> figure name (events, hours, volume); Indiana's PARAMS unless given (the state files).
    location_ok: monitoring location description -> read or not; 'Effluent Gross' lines only unless given."""
    params = PARAMS if params is None else params
    location_ok = location_ok or (lambda desc: "gross" in str(desc or "").lower())
    cells: dict[tuple, dict] = defaultdict(dict)
    names = {}
    for (permit, code), res in results.items():
        names[permit] = res.get("CWPName")
        for f in res.get("PermFeatures") or []:
            feat = str(f.get("PermFeatureNmbr") or "").upper()
            for par in f.get("Parameters") or []:
                if str(par.get("ParameterCode")) not in params:
                    continue
                rows = par.get("DischargeMonitoringReports") or []
                if not location_ok(par.get("MonitoringLocationDesc")) or \
                        "external" not in str(f.get("PermFeatureTypeDesc") or "external").lower():
                    stats["skipped_not_effluent_gross"][f"{permit}:{feat}"] += len(rows)
                    continue
                if common.outfall_key(permit, feat) not in reg:
                    stats["skipped_not_cso_outfall"][f"{permit}:{feat}"] += len(rows)
                    continue
                name = params[str(par["ParameterCode"])]
                for row in rows:
                    pend = row.get("MonitoringPeriodEndDate")
                    if not pend:
                        continue
                    try:
                        ym = month_bounds(pend)[2]
                    except ValueError:
                        stats["unparsed_period"][f"{permit}:{feat}:{pend}"] += 1
                        continue
                    new = dict(row, _pend=pend, _param=par.get("ParameterDesc"))
                    prev = cells[(permit, feat, ym)].get(name)
                    if prev is None or revision_key(row) > _rank(prev):
                        cells[(permit, feat, ym)][name] = new
                    elif revision_key(row) == _rank(prev) and evidence(row) not in _evidences(prev):
                        # equally ranked rows that disagree: neither is chosen (review 2026-11-14 P2-7); the
                        # parameter is unknown this run whatever order the answer gives them
                        rows_ = prev.get("_conflict") or [prev]
                        cells[(permit, feat, ym)][name] = {
                            "_conflict": sorted(rows_ + [new], key=lambda x: str(evidence(x))),
                            "_pend": pend, "_param": par.get("ParameterDesc"), "_rank": revision_key(row)}
                        stats["conflicting_equal_revisions"][f"{permit}:{feat}:{ym}:{name}"] += 1
    return dict(cells), names


def evidence(row: dict) -> tuple:
    """What a DMR row says: (its value, its NODI code)."""
    return num(row.get("DMRValueNmbr")), str(row.get("NODICode") or "").upper()


def _rank(entry: dict) -> tuple:
    return entry["_rank"] if "_conflict" in entry else revision_key(entry)


def _evidences(entry: dict) -> list[tuple]:
    return [evidence(x) for x in entry["_conflict"]] if "_conflict" in entry else [evidence(entry)]


EVIDENCE_FIELDS = ("DMRValueId", "DMRValueNmbr", "DMRUnitDesc", "NODICode", "NODIDesc", "ValueReceivedDate",
                   "VersionNmbr", "StatisticalBases", "FiguredAs")


def _ev_key(permit, feat, ym, name) -> str:
    return f"{permit}|{feat}|{ym}|{name}"


def _ev_row(row: dict) -> dict:
    return {k: row.get(k) for k in EVIDENCE_FIELDS if row.get(k) not in (None, "")} | \
        ({"parameter": row.get("_param") or row.get("parameter")} if row.get("_param") or row.get("parameter") else {})


def _ev_entry(entry: dict) -> dict:
    """The stored form of a cell entry: a row, or {conflict: [rows], rank} for equally ranked rows that disagree."""
    if "_conflict" in entry:
        return {"conflict": [_ev_row(x) for x in entry["_conflict"]], "rank": list(entry["_rank"])}
    return _ev_row(entry)


def _ev_rank(stored: dict) -> tuple:
    return tuple(stored["rank"]) if "conflict" in stored else revision_key(stored)


def _ev_evidences(stored: dict) -> list[tuple]:
    return [evidence(x) for x in stored["conflict"]] if "conflict" in stored else [evidence(stored)]


def merge_previous(cells: dict, prev_records: list[dict], stats: dict, store: dict | None = None) -> dict:
    """Reconcile this run's cells with every earlier run's evidence, parameter by parameter (verification
    2026-11-15 P1-1), and return the updated evidence store (kept in CACHE_FILE under 'evidence', read on --refresh
    too, so neither a replaced cached answer nor a withdrawn record loses it). For each outfall, month and parameter:
    the higher revision_key wins whichever run read it (a version-1 row read later never overrides a version-2 row
    read earlier, a zero or NODI C correction included); equally ranked rows that disagree, in one run or across
    runs, are a conflict (the parameter is unknown until a higher revision settles it); a parameter this run's
    answer leaves out keeps the earlier row (re-review 2026-11-14 P1-1). The earlier rows come from the store, and
    for a file written before the store, from the previous records' raw.dmr. A month absent from this run's answer
    altogether is carried whole by main()."""
    store = dict(store or {})
    for r in prev_records:                     # files written before the store: their records' rows are evidence
        raw = r.get("raw") or {}
        feat = raw.get("permit_feature") or r.get("outfall_id")
        for name, row in (raw.get("dmr") or {}).items():
            store.setdefault(_ev_key(r.get("npdes_permit"), feat, raw.get("month"), name), _ev_row(row))
    for (permit, feat, ym), cell in cells.items():
        pend = next(iter(cell.values()))["_pend"]
        for name in PARAMS.values():
            k = _ev_key(permit, feat, ym, name)
            old, cur = store.get(k), cell.get(name)
            if old is None:
                if cur is not None:
                    store[k] = _ev_entry(cur)
                continue
            back = None
            if cur is None or ("_conflict" not in cur and not _says(cur)) or _rank(cur) < _ev_rank(old):
                back = old             # missing, saying nothing (another NODI code), or a lower revision
            elif _rank(cur) == _ev_rank(old):
                evs = sorted(set(_ev_evidences(old)) | set(_evidences(cur)), key=str)
                if len(evs) > 1:
                    rows = {str(evidence(x)): x for x in
                            (old["conflict"] if "conflict" in old else [old]) +
                            [_ev_row(x) for x in (cur["_conflict"] if "_conflict" in cur else [cur])]}
                    if "_conflict" not in cur or len(rows) > len(cur["_conflict"]):
                        stats["conflicting_equal_revisions"][f"{permit}:{feat}:{ym}:{name}"] += 1
                    cell[name] = {"_conflict": [rows[e] for e in sorted(rows)], "_pend": pend,
                                  "_param": (cur.get("_param") if cur else None), "_rank": _rank(cur)}
            if back is not None:
                if "conflict" in back:
                    cell[name] = {"_conflict": back["conflict"], "_pend": pend, "_param": None,
                                  "_rank": tuple(back["rank"])}
                else:
                    cell[name] = dict(back, _pend=pend, _param=back.get("parameter"), _from_previous_run=True)
                    stats["parameters_kept_from_previous_run"][f"{permit}:{feat}:{ym}:{name}"] += 1
            store[k] = _ev_entry(cell[name])
    return store


def _says(row: dict) -> bool:
    return num(row.get("DMRValueNmbr")) is not None or str(row.get("NODICode") or "").upper() == "C"


def figures(cell: dict) -> dict:
    """{events, hours, volume_mgal, no_discharge, received, unit_volume} of one outfall-month."""
    out = {"no_discharge": False, "received": None}
    vals = {}
    # a figure that is not the month's own total (row FiguredAs, the state files only): above zero it says there was a
    # discharge, never how much, so it is no count, hours or volume and its filed form is written out (out["filed"])
    marked, filed = {}, {}
    for name, row in cell.items():
        if "_conflict" in row:
            continue
        if str(row.get("NODICode") or "").upper() == "C":
            vals[name] = 0.0
            out["no_discharge"] = True
        elif row.get("NODICode") or row.get("NODIDesc"):
            continue
        else:
            v = num(row.get("DMRValueNmbr"))
            if v is not None and row.get("FiguredAs") and v != 0:
                marked[name], filed[name] = v, str(row["FiguredAs"])
            elif v is not None:
                vals[name] = v
        rec = ddmon(row.get("ValueReceivedDate"))
        if rec and (out["received"] is None or rec > out["received"]):
            out["received"] = rec
    out["events"], out["hours"] = vals.get("events"), vals.get("hours")
    vol = vals.get("volume")
    unit = (cell.get("volume") or {}).get("DMRUnitDesc") or "Mgal"
    out["volume_gal"] = round(vol * MGAL[unit]) if vol is not None and unit in MGAL else None
    out["volume_mgal"] = vol if unit in ("Mgal", "MG", "MG/mo", "Mgal/mo") else None
    out["volume_raw"] = None if vol is None else f"{vol:g} {unit}"
    out["any"] = any((x or 0) > 0 for x in (out["events"], out["hours"], vol)) or any(v > 0 for v in marked.values())
    out["said"] = bool(vals) or bool(marked)
    out["filed"] = filed
    # equally ranked rows that disagree (verification 3, 2026-11-15, P2-1): what each filed, and whether any of them
    # files a discharge; a disputed discharge is a discharge month with that figure unknown, whatever order the rows
    # arrived in, never a no-discharge finding
    out["conflicts"] = {name: sorted({_filed(x) for x in row["_conflict"]}, key=_filed_order)
                        for name, row in sorted(cell.items()) if "_conflict" in row}
    out["disputed"] = any((num(x.get("DMRValueNmbr")) or 0) > 0
                          for row in cell.values() if "_conflict" in row for x in row["_conflict"])
    return out


def _filed(row: dict) -> str:
    """What one DMR row filed, as text: its value, 'NODI C' or another NODI code, or 'nothing'."""
    v = num(row.get("DMRValueNmbr"))
    if v is not None:
        return f"{v:g}"
    code = str(row.get("NODICode") or "").upper()
    return f"NODI {code}" if code else "nothing"


def _filed_order(text: str) -> tuple:
    v = num(text) if text[:1].isdigit() or text[:1] == "-" else None
    return (0, v, "") if v is not None else (1, 0.0, text)


def _zero(row: dict) -> bool:
    """A row that files no discharge: a zero or NODI C."""
    return str(row.get("NODICode") or "").upper() == "C" or num(row.get("DMRValueNmbr")) == 0


def carried_params(cells: dict) -> dict[tuple, set]:
    """(permit, feature) -> the parameters the outfall's DMRs carry in any month read."""
    carried: dict[tuple, set] = defaultdict(set)
    for (permit, feat, _), cell in cells.items():
        carried[(permit, feat)] |= set(cell)
    return carried


def no_discharge_confirmed(cell: dict, names: set) -> bool:
    """A month of no discharge on complete evidence: no figure above zero, none disputed, and every parameter the
    outfall carries (names) present and filed as a zero or NODI C, an equally ranked pair that differs only in form
    (0 and NODI C) included; a parameter missing, filed with another NODI code or disputed is not a finding."""
    fg = figures(cell)
    if fg["any"] or fg["disputed"] or not names:
        return False
    return all(name in cell and all(_zero(x) for x in cell[name].get("_conflict") or [cell[name]]) for name in names)


def volume_text(fg: dict, ym: str) -> str:
    if fg.get("disputed"):
        # a disputed discharge month: no figure is written as "N discharge events", so the status build never reads
        # a zero from it (build/status.py monthly_mark: a month it cannot read counts as a discharge)
        label = {"events": "discharge event count", "hours": "hours", "volume": "volume"}
        parts = [f"{label[n]} filed as " + " and ".join(fg["conflicts"][n]) + " in equally ranked reports"
                 if n in fg["conflicts"] else f"{label[n]} {fg[k]:g}" + (" million gallons" if n == "volume" else "")
                 for n, k in (("events", "events"), ("hours", "hours"), ("volume", "volume_mgal"))
                 if n in fg["conflicts"] or fg[k] is not None]
        parts += [t for n, t in sorted((fg.get("filed") or {}).items()) if n not in fg["conflicts"]]
        return (f"monthly DMR totals for {ym} in conflict, one report filing a discharge: " + "; ".join(parts)
                + " (the figures in conflict are unknown until a higher revision settles them)")
    parts = []
    if fg["events"] is not None:
        n = fg["events"]
        parts.append(f"{n:g} discharge event{'s' if n != 1 else ''}")
    if fg["hours"] is not None:
        parts.append(f"{fg['hours']:g} hours")
    if fg["volume_mgal"] is not None:
        parts.append(f"{fg['volume_mgal']:g} million gallons")
    elif fg["volume_raw"]:
        parts.append(fg["volume_raw"])
    filed = [t for _, t in sorted((fg.get("filed") or {}).items())]
    if not filed:
        text = ", ".join(parts) + f" in {ym} (monthly DMR totals)"
    else:
        # a figure that is not the month's total (the state files): written as filed after the month's own figures
        text = (f"{', '.join(parts)} in {ym}; " if parts else f"{ym}: ") + "; ".join(filed) + \
            (", not monthly totals" if len(filed) > 1 else ", not a monthly total")
    if fg.get("conflicts"):
        label = {"events": "discharge event count", "hours": "hours", "volume": "volume"}
        text += "; " + "; ".join(f"the {label.get(n, n)} is in conflict: equally ranked reports filed "
                                 + " and ".join(v) for n, v in fg["conflicts"].items())
    return text


def latest_months(cells: dict) -> dict[str, dict]:
    """{"<permit>|<outfall>": {month, discharged, events, received_at}}: each outfall's latest month the DMRs speak of,
    no-discharge months included (build/status.py latest_observations)."""
    out: dict[str, dict] = {}
    # the parameters each outfall's DMRs carry (any month read): a month with no discharge clears an earlier
    # monthly mark only when every one of them is a zero or NODI C, none missing, in conflict or another NODI code
    # (verification 2026-11-15 P2-3: zero hours with events and volume missing is not a confirmed no-discharge month);
    # a month where an equally ranked row files a discharge is a discharge month (verification 3 P2-1)
    carried = carried_params(cells)
    for (permit, feat, ym), cell in cells.items():
        fg = figures(cell)
        discharged = fg["any"] or fg["disputed"]
        if not discharged and not no_discharge_confirmed(cell, carried[(permit, feat)]):
            continue
        k = f"{permit}|{feat}"
        cur = out.get(k)
        if cur is None or ym > cur["month"]:
            out[k] = {"month": ym, "discharged": discharged, "events": fg["events"], "received_at": fg["received"],
                      **({"conflicting": sorted(fg["conflicts"])} if fg["conflicts"] else {})}
    return dict(sorted(out.items()))


def store_cells(store: dict) -> dict:
    """The evidence store (merge_previous) as cells: (permit, feature, month) -> {param: row or conflict}, every
    outfall-month any run has read, with its winning row per parameter."""
    cells: dict[tuple, dict] = defaultdict(dict)
    for k, stored in store.items():
        permit, feat, ym, name = k.split("|")
        cells[(permit, feat, ym)][name] = (
            {"_conflict": stored["conflict"], "_rank": tuple(stored["rank"]), "_pend": None}
            if "conflict" in stored else dict(stored, _pend=None))
    return dict(cells)


def reconcile_latest(prev: dict, store: dict, stats: dict) -> dict:
    """meta.latest_month_by_outfall from the evidence kept across runs (verification 2, 2026-11-15, P2-1): the
    parameters an outfall reports are those any run has read for it, so a newer month this run's answer holds only
    in part never clears an established monthly mark; and a no-discharge finding whose evidence has since become
    conflicting (or incomplete) is withdrawn and recomputed from the months that remain (counted in
    meta.no_discharge_findings_withdrawn). An earlier observation of a month the store holds no evidence for (a
    file written before the store) is kept while it is the newer one."""
    sc = store_cells(store)
    derived = latest_months(sc)
    known: dict[str, set] = defaultdict(set)
    for permit, feat, ym in sc:
        known[f"{permit}|{feat}"].add(ym)
    out = {}
    for k in sorted(set(prev) | set(derived)):
        p, v = prev.get(k), derived.get(k)
        pm = (p or {}).get("month") if isinstance(p, dict) else None
        if pm and pm not in known[k] and (v is None or pm > v["month"]):
            out[k] = p
            continue
        if pm and p.get("discharged") is True and (v is None or v["month"] < pm):
            # a discharge month whose newer filing reads zero only in part: its record is kept (main()), and so is
            # its observation, until a complete no-discharge filing or a higher revision (verification 3 P2-1)
            out[k] = dict(p, no_discharge_unconfirmed=True)
            continue
        if pm and p.get("discharged") is False and (v is None or v["month"] < pm or
                                                     (v["month"] == pm and v["discharged"])):
            stats["no_discharge_findings_withdrawn"][f"{k}:{pm}"] += 1
        if v is not None:
            out[k] = v
    return out


def build_records(cells: dict, names: dict, reg: dict, disc: dict, stats: dict, feed: dict | None = None) -> list[dict]:
    """The records of the outfall-months with a discharge. feed (the state files, ingest/echo_dmr_cso_states.py):
    source_id, authority, zone (o, lat, lon -> IANA zone), source_url (permit -> address), material; Indiana's
    otherwise."""
    feed = feed or {}
    source_id, authority = feed.get("source_id") or SOURCE_ID, feed.get("authority") or AUTHORITY
    zone_of = feed.get("zone") or (lambda o, lat, lon: zones.indiana_zone(county=o.get("county"), lat=lat, lon=lon))
    url_of = feed.get("source_url") or (lambda permit: f"https://echo.epa.gov/effluent-charts#{permit}")
    records = []
    for (permit, feat, ym), cell in sorted(cells.items()):
        fg = figures(cell)
        if not fg["any"] and not fg["disputed"]:
            stats["no_discharge_months" if fg["said"] else "no_value_months"][permit] += 1
            continue
        if fg["disputed"]:
            stats["disputed_discharge_months"][f"{permit}:{feat}:{ym}"] += 1
            fg = dict(fg, volume_gal=None)        # a volume of a month in dispute is not counted
        pend = next(iter(cell.values()))["_pend"]
        start, end, _ = month_bounds(pend)
        o = reg.get(common.outfall_key(permit, feat)) or {}
        d = disc.get(permit) or {}
        lat, lon = o.get("lat"), o.get("lon")
        point_note = None
        if str(o.get("coords_from") or "") == "facility" and lat is not None:
            # EPA gives this outfall only the plant's point: not the outfall's place (review 2026-11-14 P1-4)
            point_note, lat, lon = "the registry gives only the treatment plant's point for this outfall: not used", None, None
        if lat is not None:
            lat, lon = round(float(lat), 3), round(float(lon), 3)
        slug = o.get("water_slug")
        tz = zone_of(o, lat, lon)
        vol_note = None
        if fg["volume_gal"] and fg["hours"] and fg["volume_gal"] / 1e6 / fg["hours"] > MAX_MGAL_PER_HOUR:
            vol_note = (f"the filed volume ({fg['volume_raw']} in {fg['hours']:g} hours) implies more than "
                        f"{MAX_MGAL_PER_HOUR:g} million gallons an hour, likely gallons filed as million gallons: "
                        "kept as filed in the text, not counted as a volume")
            fg = dict(fg, volume_gal=None)
        raw = {"month": ym, "permit_feature": feat,
               "events": fg["events"], "hours": fg["hours"], "volume": fg["volume_raw"],
               "dmr": {name: {k: row.get(k) for k in RAW_FIELDS} | {"parameter": row.get("_param")}
                       | {k: row[k] for k in STATE_FILE_FIELDS if row.get(k) not in (None, "")}
                       | ({"from_previous_run": True} if row.get("_from_previous_run") else {})
                       for name, row in sorted(cell.items()) if "_conflict" not in row},
               **({"conflicting_rows": sorted(fg["conflicts"]), "conflicts": fg["conflicts"],
                   "conflict_note": ("equally ranked DMR rows for this month disagree; the figure is unknown until "
                                     "a higher revision settles it" + ("; one of them files a discharge, so the month "
                                     "is kept as a discharge month" if fg["disputed"] else ""))}
                  if fg["conflicts"] else {}),
               "receiving_water_registry": o.get("receiving_water_echo"),
               "outfall_registry_file": o.get("_file"), "outfall_status": o.get("outfall_status"),
               "county": o.get("county"), "time_zone": tz, **({"volume_note": vol_note} if vol_note else {}),
               **({"point_note": point_note} if point_note else {}),
               # the chart builder's monthly measures (build/charts.py total_measures): events and hours
               "parameters": {k: {"DMRValueNmbr": v} for k, v in (("events", fg["events"]), ("duration", fg["hours"]))
                              if v is not None},
               "note": feed.get("note") or ("the operator's monthly DMR totals for this outfall (events, hours, million "
                                            "gallons), not an individual discharge: no day is given")}
        records.append(event(
            source_id=source_id, source_record_id=f"{permit}:{feat}:{ym}", event_type="cso", status="ended",
            discharger_id=d.get("id"), discharger_name=d.get("name") or names.get(permit), npdes_permit=permit,
            outfall_id=feat, outfall_name=o.get("outfall_name"),
            waterbody_text=o.get("receiving_water_echo"),
            water_slugs=[slug] if slug else [], water_match="outfall_registry" if slug else "none",
            lat=lat, lon=lon, coord_source="outfall_registry" if lat is not None else None,
            started_at=start, ended_at=end, time_precision="month", reported_at=fg["received"],
            material="combined sewage and stormwater", volume_gal=fg["volume_gal"],
            volume_text=volume_text(fg, ym), estimate_flag="unknown",
            authority=authority, source_url=url_of(permit), raw=raw,
        ))
    records.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return records


def median_lag_days(records: list[dict]) -> float | None:
    lags = []
    for r in records:
        try:
            lags.append((date.fromisoformat(r["reported_at"]) - date.fromisoformat(r["ended_at"])).days)
        except (TypeError, ValueError):
            continue
    return statistics.median(lags) if lags else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--refresh", action="store_true", help="ignore the cached responses")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since)
    today = datetime.now(UTC).date()

    reg = registry_outfalls()
    permits = permits_to_read(reg)
    cache = {} if args.refresh else load_cache()
    keys = [(p, c) for p in permits for c in PARAMS]
    # the oldest (or never) fetched first, so a run cut short by the request budget leaves the freshest for later
    keys.sort(key=lambda k: ((cache.get(f"{k[0]}-{k[1]}") or {}).get("fetched") or "", k))
    results, fetch_log, live = {}, {}, 0
    failures_in_a_row, stopped = 0, False
    for permit, code in keys:
        key = f"{permit}-{code}"
        e, how = cached(cache, permit, code, since, today)
        if e is None and (stopped or live >= MAX_LIVE_REQUESTS):
            e, how = cached(cache, permit, code, since, today, stale_ok=True)
            if e is None:
                fetch_log[key] = ("failed (not asked: stopped after "
                                  f"{MAX_CONSECUTIVE_FAILURES} failures)" if stopped else
                                  "not asked this run (request budget); no earlier answer")
                continue
        if e is not None:
            fetch_log[key] = how
            if e.get("invalid"):
                fetch_log[key] = f"not in ECHO ({e['invalid']})"
            else:
                results[(permit, code)] = e["results"]
            continue
        if live:
            time.sleep(SLEEP_S)
        live += 1
        res, how = fetch(permit, code, since)
        fetch_log[key] = how
        if how.startswith("not in ECHO"):
            cache[key] = {"fetched": today.isoformat(), "since": since.isoformat(), "invalid": how[13:-1]}
            failures_in_a_row = 0
        elif res is None:
            failures_in_a_row += 1
            stopped = failures_in_a_row >= MAX_CONSECUTIVE_FAILURES
            old, _ = cached(cache, permit, code, since, today, stale_ok=True)
            if old is not None and not old.get("invalid"):
                results[(permit, code)] = old["results"]
        else:
            failures_in_a_row = 0
            cache[key] = {"fetched": today.isoformat(), "since": since.isoformat(), "results": compact(res)}
            results[(permit, code)] = cache[key]["results"]
    evidence_store = (read_json(CACHE_FILE, {}) or {}).get("evidence") or {}

    def save_cache(store: dict) -> None:
        write_json(CACHE_FILE, {"source_id": SOURCE_ID, "about": "compact ECHO answers per permit and parameter "
                                "(ingest/in_echo_cso_monthly.py compact): the run-to-run cache; 'evidence' keeps the "
                                "winning DMR row of every outfall, month and parameter ever read (merge_previous)",
                                "answers": cache, "evidence": dict(sorted(store.items()))})
    save_cache(evidence_store)

    if not results:
        write_events(SOURCE_ID, [], ok=False, error="all requests failed")
        print(f"{SOURCE_ID}: all requests failed", file=sys.stderr)
        return 1

    return finish(results, reg, dischargers(), since=args.since, permits=permits, fetch_log=fetch_log,
                  evidence_store=evidence_store, save_store=save_cache)


def finish(results: dict, reg: dict, disc: dict, *, since: str, permits: list[str], fetch_log: dict,
           evidence_store: dict, save_store, feed: dict | None = None, meta_extra: dict | None = None) -> int:
    """Records, reconciliation with the previous file and the events file, from the answers read (results, keyed
    (permit, parameter code), in the effluent-chart shape compact() keeps). Indiana's main() and the state files
    (ingest/echo_dmr_cso_states.py, feed: source_id, params, authority, zone, source_url, cadence, note) share it.
    fetch_log values starting "failed" make the run not ok (the previous records kept); save_store(store) keeps the
    evidence store (merge_previous). Returns the exit code."""
    feed = feed or {}
    source_id = feed.get("source_id") or SOURCE_ID
    params = feed.get("params") or PARAMS
    stats = defaultdict(Counter)
    cells, names = collect(results, reg, stats, params, feed.get("location_ok"))
    prev_doc = read_json(common.EVENTS_DIR / f"{source_id}.json", {}) or {}
    store = merge_previous(cells, prev_doc.get("records") or [], stats, evidence_store)
    save_store(store)
    records = build_records(cells, names, reg, disc, stats, feed)
    carried = carried_params(store_cells(store))
    # reconcile with the previous run (review 2026-11-14 P1-2): a month the source no longer lists at all is kept,
    # marked missing from the source; a month the source now reports as no discharge is withdrawn; a month whose
    # cells now say nothing (no value, another NODI code) is kept as it was; merge_previous has already put back
    # every parameter this run's answer left out, so a month withdrawn here was corrected parameter by parameter
    ids = {r["event_id"] for r in records}
    for r in prev_doc.get("records") or []:
        if r.get("event_id") in ids:
            continue
        rk = (r.get("npdes_permit"), (r.get("raw") or {}).get("permit_feature") or r.get("outfall_id"),
              (r.get("raw") or {}).get("month"))
        cell = cells.get(rk)
        # withdrawn only on complete, conflict-free no-discharge evidence (verification 3, 2026-11-15, P2-1): every
        # parameter the outfall carries filed as zero or NODI C; a month that now reads in part, in conflict or with
        # another NODI code keeps its earlier totals, marked, until a complete or higher revision settles it
        if cell is not None and no_discharge_confirmed(cell, carried[(rk[0], rk[1])]):
            stats["months_withdrawn_by_the_source"][f"{rk[0]}:{rk[1]}:{rk[2]}"] += 1
            continue
        r = json.loads(json.dumps(r))
        if cell is not None and (figures(cell)["said"] or figures(cell)["conflicts"]):
            fg = figures(cell)
            r["raw"]["no_discharge_unconfirmed"] = {
                "since": r["raw"].get("no_discharge_unconfirmed", {}).get("since") or now_iso(),
                "conflicting_rows": sorted(fg["conflicts"]), "conflicts": fg["conflicts"],
                "note": ("a newer filing for this month reads no discharge only in part or in conflict: the earlier "
                         "totals are kept until a complete, conflict-free no-discharge report or a higher revision")}
            records.append(r)
            stats["records_kept_on_unconfirmed_no_discharge"][f"{rk[0]}:{rk[1]}:{rk[2]}"] += 1
            continue
        r["raw"].setdefault("_missing_from_source_since", now_iso())
        records.append(r)
        stats["records_carried_from_previous_run"]["records"] += 1
    records.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    latest = reconcile_latest((prev_doc.get("meta") or {}).get("latest_month_by_outfall") or {}, store, stats)
    per_permit = Counter(r["npdes_permit"] for r in records)
    meta = {"registry_ids": [source_id], "since": since,
            "parameters": {c: n for c, n in params.items()}, "permits": permits,
            "fetch": fetch_log, "records_per_permit": dict(sorted(per_permit.items())),
            "permits_without_records": sorted(set(permits) - set(per_permit)),
            "median_days_month_end_to_receipt": median_lag_days(records),
            **{k: dict(v) for k, v in stats.items()},
            "cadence": feed.get("cadence") or (f"cached per permit and parameter for {CACHE_DAYS} days; DMRs "
                                               "reach ECHO weeks after the month"),
            "latest_month_by_outfall": dict(sorted(latest.items())),
            "history_only": "month precision: the monthly mark, never red or yellow",
            **(meta_extra or {})}
    failed = {k: v for k, v in fetch_log.items() if v.startswith("failed")}
    meta["not_asked_this_run"] = sorted(k for k, v in fetch_log.items() if v.startswith(("not asked", "stale")))
    if failed:
        err = f"{len(failed)} requests failed: " + "; ".join(f"{k} {v}" for k, v in list(failed.items())[:10])
        path = common.EVENTS_DIR / f"{source_id}.json"
        prev = read_json(path, {}) or {}
        if prev.get("records") or not records:
            write_events(source_id, [], ok=False, error=err, meta=meta)
        else:
            write_json(path, {"source_id": source_id, "fetched_at": now_iso(), "ok": False, "error": err,
                              "last_ok_at": None, "meta": meta, "count": len(records), "records": records})
        print(f"{source_id}: run not ok ({err})", file=sys.stderr)
        return 1
    path = write_events(source_id, records, meta=meta)
    print(f"{source_id}: {len(records)} outfall-months from {len(per_permit)} permits -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
