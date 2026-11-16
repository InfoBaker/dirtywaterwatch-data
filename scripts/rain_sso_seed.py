"""Build the seed copy data/rain-levels-sso.json from the site's saved yearly report exports (build.rain_sso.build, the
same code the daily pass runs on the events files), for when the pipeline's events are not on this machine.

    pipeline/.venv/bin/python -I scripts/rain_sso_seed.py --csv DIR --iem DIR --coverage FILE [--today YYYY-MM-DD]

--csv: a folder of all-reports-<year>.csv (https://dirtywaterwatch.org/csv/all-reports-<year>.csv).
--iem: a folder of cached NOAA MRMS daily totals, <lat>_<lon>_<year>.json, either the pipeline's cache (the point
service's answer, {"data": [{"date", "mrms_precip_in"}]}) or a list of {"date", "mrms"}. Nothing is fetched: an
operator whose point is not cached is listed as not read.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from build import rain_sso  # noqa: E402
from common import read_json  # noqa: E402

FIELDS = ("event_id", "event_type", "started_at", "ended_at", "time_precision", "duplicate_of", "source_id",
          "reported_at", "published_at", "state")


def records_from_csv(folder: Path) -> tuple[list[tuple[str, list[dict]]], dict, dict]:
    """([(source_id, records)], placements, names) from the yearly CSVs: each row as an events-file record, with its
    operator id as discharger_id and its water records as the placement."""
    csv.field_size_limit(10**9)
    by_src: dict[str, list[dict]] = {}
    placements, names, seen = {}, {}, set()
    for f in sorted(folder.glob("all-reports-*.csv")):
        with f.open(encoding="utf-8", errors="ignore") as fh:
            for row in csv.DictReader(fh):
                eid = row["event_id"]
                if eid in seen:
                    continue
                seen.add(eid)
                rec = {k: (row.get(k) or None) for k in FIELDS}
                rec["discharger_id"] = row.get("operator_id") or None
                rec["discharger_name"] = row.get("operator") or None
                rec["lat"], rec["lon"] = row.get("lat") or None, row.get("lon") or None
                by_src.setdefault(row["source_id"], []).append(rec)
                placements[eid] = {"water_slugs": [s for s in (row.get("water_slug") or "").split(";") if s],
                                   **({"duplicate_of": row["duplicate_of"]} if row.get("duplicate_of") else {}),
                                   **({"superseded": row["superseded_by"]} if row.get("superseded_by") else {})}
                if row.get("operator_id") and row.get("operator"):
                    names.setdefault(row["operator_id"], row["operator"])
    return sorted(by_src.items()), placements, names


def iem_reader(folder: Path):
    def path(lat, lon, y):
        return folder / f"{lat:.2f}_{lon:.2f}_{y}.json"

    def rows(p):
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            return [(r.get("date"), r.get("mrms_precip_in")) for r in d.get("data") or []]
        return [(r.get("date"), r.get("mrms")) for r in d or []]

    def have(lat, lon, years):
        return all(path(lat, lon, y).exists() for y in years)

    def read(lat, lon, years, offline, budget):
        out = {}
        for y in years:
            p = path(lat, lon, y)
            if p.exists():
                for d, v in rows(p):
                    if d and v is not None:
                        out[date.fromisoformat(d)] = float(v)
        return out
    return read, have


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--iem", type=Path, required=True)
    ap.add_argument("--today", default=None)
    ap.add_argument("--coverage", type=Path, required=True, help="a saved export's coverage.json (each state's grade)")
    ap.add_argument("--out", type=Path, default=rain_sso.LEVELS_SEED)
    a = ap.parse_args()
    rules = read_json(ROOT / "data" / "rules.json", {}) or {}
    sources, placements, names = records_from_csv(a.csv)
    read, have = iem_reader(a.iem)
    today = date.fromisoformat(a.today) if a.today else datetime.now(UTC).date()
    d = rain_sso.build(offline=True, today=today, now=datetime.now(UTC), sources=sources, rules=rules,
                       operator_of=lambda r: r.get("discharger_id"), placements=placements, reader=read, have=have,
                       names=names, grades=rain_sso.grades_of(json.loads(a.coverage.read_text())), out_path=a.out)
    c = d["counts"]
    print(f"rain_sso_seed: {c['operators']} operators, {c['read']} read, {c['qualify']} qualify {c['qualify_by_state']}")
    for op, e in d["operators"].items():
        if op in set(rain_sso.settings(rules)["approved"]):
            print(f"  {op}: {'QUALIFIES' if e.get('qualifies') else 'no'} lift={e.get('lift')} storms={e.get('storms')} "
                  f"followed={e.get('followed')} possible={e.get('possible_in')} likely={e.get('likely_in')} "
                  f"recent={(e.get('recent') or {}).get('followed')} newest={e.get('newest_report')} "
                  f"why={e.get('why_not')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
