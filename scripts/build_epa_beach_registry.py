#!/usr/bin/env python3
"""The EPA beach registry: one row per beach in EPA's BEACON 2.0 -> data/beaches-epa.json

    python scripts/build_epa_beach_registry.py [--from-dir DIR] [--years 2025 2026] [--out data/beaches-epa.json]

Reads four BEACON reports for each year (the current and the previous calendar year by default), live through the
session the beach-actions feed uses (pipeline/ingest/fed_beacon_beach_actions.py open_session and pull_report: the
pipeline's named client, about one second between requests) or from saved CSVs named <report>_<year>.csv
(--from-dir):
  beach-attributes                   name, county, waterbody name and type, BEACH Act flag, tier, historical, dormant,
                                     length, access, owner, start and end latitude and longitude, monitoring frequency,
                                     advisory and monitoring reporting frequency to EPA
  season-and-monitoring-frequency    swim season start, end, days and hours a day; in- and off-season monitoring
                                     frequency; monitored irregularly
  wqs-criteria                       the criteria rows (indicator, water type, measure type, value, unit, comment)
  possible-pollution-sources         sources investigated and found; the source flags (CSO, SSO, POTW, sewer line ...)
The Beach Contact Information report is never read (it names staff).
One row per beach, in the fifty states, the District of Columbia and Puerto Rico (the territories and the four tribal
programs are counted, not written): the attributes from the latest year whose attributes report lists the beach, and
each other group from the latest year whose report lists it, each group citing its report and year (`cited`). Values
are kept as BEACON gives them (dates written as ISO dates, coordinates as numbers); BEACON's Michigan criterion row
("ENTEROCOCCUS", "GM", "300") is kept as given (`notes`).
A beach's season is the state's monitoring season as filed with EPA, not a safety window.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from common import dumps_rows  # noqa: E402
from ingest import fed_beacon_beach_actions as B  # noqa: E402

OUT = ROOT / "data" / "beaches-epa.json"
REPORTS = {
    "attributes": ("beach-attributes", "BEACON Beach Attributes",
                   ("Jurisdiction", "Year", "Beach ID", "Beach Name", "StartLatitude", "StartLongitude")),
    "season": ("season-and-monitoring-frequency", "BEACON Swim Season and Monitoring Frequency",
               ("Jurisdiction", "Year", "Beach ID", "SSStart Date", "SSEnd Date")),
    "criteria": ("wqs-criteria", "BEACON WQS Criteria",
                 ("Jurisdiction", "Year", "Beach ID", "Indicator Name", "MeasureType", "MeasureValue", "MeasureUnit")),
    "possible_sources": ("possible-pollution-sources", "BEACON Possible Pollution Sources",
                         ("Jurisdiction", "Year", "Beach ID", "CSO", "SSO", "POTW")),
}
SOURCE_FLAGS = ("Runoff", "Storm", "Agri-cultural", "Algae", "Boat", "CAFO", "CSO", "SSO", "POTW", "SewerLine",
                "Septic", "Wildlife", "TBD", "Other", "Unknown")
FLAG_NAMES = {"Agri-cultural": "Agricultural", "SewerLine": "Sewer line"}
NO_COMMENT = re.compile(r"^no comments? submitted$", re.I)
TITLE = re.compile(r'title="([^"]*)"')
TAG = re.compile(r"<[^>]+>")
FILLED = {"season": lambda v: bool(v.get("start") or v.get("end")),
          "possible_sources": lambda v: bool(v.get("flags"))}
NOTES = [
    "BEACON's criteria report lists Michigan's beaches with the indicator ENTEROCOCCUS, the measure type GM and the "
    "value 300 (#/100ml); the row is kept as BEACON gives it and has not been checked against Michigan's own rule.",
    "A beach's swim season is the monitoring season the state filed with EPA, not a safety window.",
]


def text_of(v) -> str:
    return " ".join(html.unescape(TAG.sub(" ", str(v or ""))).split())


def num(v):
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def iso_date(v) -> str | None:
    """'05-15-2025' -> '2025-05-15'; anything else as given (None for blank)."""
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", s)
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else (s or None)


def blank(v) -> str | None:
    s = str(v or "").strip()
    return s or None


def kept(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def attributes(r: dict) -> dict:
    return kept({"name": blank(r.get("Beach Name")), "state": blank(r.get("Jurisdiction")), "county": blank(r.get("County")),
            "waterbody_name": blank(r.get("Waterbody Name")), "waterbody_type": blank(r.get("Waterbody Type")),
            "beach_act": blank(r.get("IsBeach ActBeach?")), "tier": blank(r.get("Tier")),
            "historical": blank(r.get("IsHistorical?")), "dormant": blank(r.get("IsDormant?")),
            "access": blank(r.get("BeachAccess")), "owner": blank(r.get("BeachOwner")),
            "length_mi": num(r.get("BeachLength (MI)")),
            "start_lat": num(r.get("StartLatitude")), "start_lon": num(r.get("StartLongitude")),
            "end_lat": num(r.get("EndLatitude")), "end_lon": num(r.get("EndLongitude")),
            "monitoring_frequency": blank(r.get("SSMonitoringFrequency")),
            "advisory_reporting_to_epa": blank(r.get("AdvisoryReportingFrequency[to EPA]")),
            "monitoring_reporting_to_epa": blank(r.get("MonitoringReportingFrequency[to EPA]"))})


def season(r: dict) -> dict:
    return kept({"start": iso_date(r.get("SSStart Date")), "end": iso_date(r.get("SSEnd Date")),
            "days": num(r.get("# ofSwimSeason (SS)days")), "hours_a_day": num(r.get("# ofhours inSSDay")),
            "in_season_monitoring": blank(r.get("SwimSeasonMonitoringFrequency")),
            "off_season_monitoring": blank(r.get("OffSeasonMonitoringFrequency")),
            "monitored_irregularly": blank(r.get("IsMonitoredIrregularly?"))})


def criterion(r: dict) -> dict:
    c = kept({"indicator": blank(r.get("Indicator Name")), "water_type": blank(r.get("Water Type")),
              "measure_type": blank(r.get("MeasureType")), "value": blank(r.get("MeasureValue")),
              "unit": blank(r.get("MeasureUnit"))})
    com = blank(r.get("Criteria Comments"))
    if com and not NO_COMMENT.match(com):
        c["comment"] = com
    return c


def sources(r: dict) -> dict:
    flags, notes = {}, {}
    for k in SOURCE_FLAGS:
        raw = r.get(k) or ""
        v = text_of(raw)
        if v:
            flags[FLAG_NAMES.get(k, k)] = v
            t = TITLE.search(raw)
            if t and html.unescape(t.group(1)).strip():
                notes[FLAG_NAMES.get(k, k)] = html.unescape(t.group(1)).strip()
    out = kept({"investigated": blank(r.get("Poll.SourcesInvesti-gated?")), "found": blank(r.get("Poll. SourcesFound?")),
                "flags": flags})
    if notes:
        out["flag_notes"] = notes
    return out


def read_reports(years: list[int], from_dir: Path | None, sess=None, sleep=None) -> dict:
    """{year: {group: [rows]}} for each year and report."""
    import time
    out = {}
    for y in years:
        out[y] = {}
        sid = None
        for group, (report, _, cols) in REPORTS.items():
            if from_dir is not None:
                p = from_dir / f"{report}_{y}.csv"
                text = p.read_text(encoding="utf-8-sig") if p.exists() else None
            else:
                if sid is None:
                    sid = B.open_session(sess, y, sleep or time.sleep)
                text = B.pull_report(sess, sid, report, cols, sleep or time.sleep)
            out[y][group] = B.rows_of(text) if text else []
    return out


def build(data: dict, built: str) -> dict:
    years = sorted(data, reverse=True)          # the latest year first: its row wins
    beaches, out_scope = {}, Counter()
    groups = {"season": season, "possible_sources": sources}
    for y in years:
        for r in data[y].get("attributes") or []:
            bid, st = blank(r.get("Beach ID")), str(r.get("Jurisdiction") or "").upper()
            if not bid:
                continue
            if st not in B.IN_SCOPE:
                if bid not in beaches:
                    out_scope[st or "(none)"] += 1
                continue
            if bid in beaches:
                continue
            beaches[bid] = {"beach_id": bid, **attributes(r),
                            "cited": {"attributes": {"report": REPORTS["attributes"][1], "year": y}}}
    # a group from the latest year whose report fills it for the beach (a season with a date, a source flag set), else
    # from the latest year that lists the beach at all: a year not yet filed lists the beach with the group blank
    for filled_only in (True, False):
        for y in years:
            for group, fn in groups.items():
                for r in data[y].get(group) or []:
                    b = beaches.get(blank(r.get("Beach ID")))
                    if b is None or group in b:
                        continue
                    v = fn(r)
                    if filled_only and not FILLED[group](v):
                        continue
                    b[group] = v
                    b["cited"][group] = {"report": REPORTS[group][1], "year": y}
    for y in years:                             # the criteria rows of the latest year that lists any for the beach
        crit: dict[str, list] = {}
        for r in data[y].get("criteria") or []:
            bid = blank(r.get("Beach ID"))
            if bid in beaches and "criteria" not in beaches[bid]:
                c = criterion(r)
                if c not in crit.setdefault(bid, []):
                    crit[bid].append(c)
        for bid, rows in crit.items():
            beaches[bid]["criteria"] = rows
            beaches[bid]["cited"]["criteria"] = {"report": REPORTS["criteria"][1], "year": y}
    rows = sorted(beaches.values(), key=lambda b: (b["state"] or "", b["beach_id"]))
    for b in rows:                              # the groups in one order, the citations last
        b["cited"] = b.pop("cited")
    per_state = Counter(b["state"] for b in rows)
    return {
        "doc": ("EPA's beach registry from BEACON 2.0: one row per beach the states filed with EPA, in the fifty "
                "states, the District of Columbia and Puerto Rico. Each group of fields cites its BEACON report and "
                "year (cited). Built by scripts/build_epa_beach_registry.py."),
        "source": "U.S. EPA BEACON 2.0 (https://beacon.epa.gov/ords/beacon2/r/beacon_apex/beacon2/), as reported by "
                  "each state's beach program",
        "licence": "U.S. EPA, public domain",
        "built": built, "years": sorted(data), "notes": NOTES,
        "counts": {"beaches": len(rows), "by_state": dict(sorted(per_state.items())),
                   "with_point": sum(1 for b in rows if b.get("start_lat") is not None or b.get("end_lat") is not None),
                   "with_season": sum(1 for b in rows if (b.get("season") or {}).get("start")),
                   "with_criteria": sum(1 for b in rows if b.get("criteria")),
                   "out_of_scope": dict(sorted(out_scope.items()))},
        "beaches": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-dir", type=Path, help="saved CSVs <report>_<year>.csv instead of BEACON")
    ap.add_argument("--years", type=int, nargs="+", help="calendar years (default: the previous and the current)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    years = args.years or B.refresh_years()
    sess = None if args.from_dir else B.new_session()
    data = read_reports(years, args.from_dir, sess)
    if not any(data[y].get("attributes") for y in years):
        print("no beach attributes read: nothing written", file=sys.stderr)
        return 1
    doc = build(data, datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(dumps_rows(doc, ("beaches",)))
    tmp.replace(args.out)
    c = doc["counts"]
    print(f"{args.out}: {c['beaches']} beaches ({c['with_point']} with a point, {c['with_season']} with a season, "
          f"{c['with_criteria']} with criteria); out of scope {sum(c['out_of_scope'].values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
