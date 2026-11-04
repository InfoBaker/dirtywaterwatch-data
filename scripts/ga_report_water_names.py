"""research/ga/receiving-waters-missing.json rebuilt from Georgia's whole report history: every receiving-water name
EPD's spill list (ga-epd-spills, the daily list and every dated posting the backfill read) and EPA's Sewer Overflow and
Bypass Event reports for GA permits (echo-sewer-overflow) give, for `python -m ingest.waters_from_nhd --names ...
--state GA`.

Usage (after the Georgia feeds have written data/build/events; nothing is fetched):
    pipeline/.venv/bin/python -I scripts/ga_report_water_names.py [--events DIR] [--out FILE] [--no-places]

A name is a record's waterbody_text split at semicolons (EPA's module joins several receiving waters so), compared
case and punctuation aside (words kept apart: key()). A name is counted once per spill: an EPA report EPD's list also gives (duplicate_of, the
ingester's pairing) and an EPD row a corrected row replaced (duplicate_of) are one spill with the row they name, and a
spill whose two reports spell the water differently counts once for each spelling's name. Reports that name no water
are not counted: EPD's blank 'waterway impacted', and every report the status build counts as naming no receiving
water (its no_receiving_water: 'Not Applicable', 'N/A', 'Did Not Enter State Waters'). Every name is a row, whether or not a water record holds it: the
names pass moves a name the status resolver already places on its record to `resolved` with nothing built, and gives
every other name a record or its reason, at each place its reports give (2026-11-04 final audit, P1-1: the names list
of six postings missed 46 names with no record, Nancy Creek and Utoy Creek the largest, and 22 whose record the
resolver could not choose or reach, Butler Creek the largest).

The file is merged, never overwritten: a row or resolved name already in it keeps every field it has (its reason,
kind, parts, records, places, how and slugs), its `reports` becomes the count over the whole history (a name no report
now gives keeps its count) and its `seen_in` gains the feeds that now give it. A new name is a row {name, reports,
seen_in, kind}. Then the places (--add-places, nothing fetched): each row's points and towns from the reports and their
operators, which choose the record where two waters share a name (Butler Creek at Augusta and at Kennesaw).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from build import status as S  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

EVENTS = ROOT / "data" / "build" / "events"
OUT = ROOT / "research" / "ga" / "receiving-waters-missing.json"
EPD, EPA = "ga-epd-spills", "echo-sewer-overflow"
SEEN = {EPD: "EPD list", EPA: "EPA reports"}
KINDS = ("named water", "tributary of a named water", "storm system or not a named water")
ABOUT = ("Receiving-water names in Georgia's spill reports (EPD's Municipal Sewage Spills list: the daily list and "
         "every dated posting from {first} to {last}, {epd} records; and EPA's Sewer Overflow and Bypass Event reports "
         "for GA permits, {epa} records, {paired} of them the same spill as an EPD row) as typed (case and punctuation "
         "ignored), each counted once per spill, with the number of spills giving it: every name, whether or not a "
         "water record holds it, so each has a record or a stated reason. Spelling variants of a held water "
         "(Polebridge Creek, Sugar Crek, Ocmuglee) are listed as typed so an alias can be added. Built by "
         "scripts/ga_report_water_names.py.")


def key(name) -> str:
    """A name with case and punctuation aside, its words kept apart ('NANCY CREEK' is 'Nancy Creek'; 'SOUTHRIVER' is not
    'South River', which a record holds: the names pass tells such a spelling apart and asks for an alias)."""
    return " ".join(re.findall(r"[a-z0-9]+", str(name or "").lower().replace("'", "").replace("\u2019", "")))


def split_names(text) -> list[str]:
    """The water names of one waterbody text, as typed, once each (case and punctuation aside)."""
    out = {}
    for x in str(text or "").split(";"):
        x = " ".join(x.split()).strip(" ,.")
        if x and key(x) and key(x) not in out:
            out[key(x)] = x
    return list(out.values())


def ga_records(events_dir: Path) -> list[dict]:
    """EPD's records and EPA's records for GA permits, from the feeds' event files."""
    out = []
    for sid in (EPD, EPA):
        p = Path(events_dir) / f"{sid}.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text()).get("records") or []:
            if sid == EPA and not str(r.get("npdes_permit") or "").upper().startswith("GA"):
                continue
            out.append({**r, "source_id": r.get("source_id") or sid})
    return out


def with_a_water(records: list[dict], resolver=None) -> list[dict]:
    """The records that name a receiving water: a waterbody text the status build does not read as naming none
    (Resolver.resolve's no_receiving_water: a placeholder, "did not reach", the source's own no-water flag)."""
    if resolver is None:
        waters = S.load_waters(include_nhd=True)
        S._STATES = S.derive_states(waters, S.load_rules(), live_only=False) | {"GA"}
        resolver = S.make_resolver(waters)
    out = []
    for r in records:
        if not split_names(r.get("waterbody_text")):
            continue
        if resolver.resolve(r).get("no_receiving_water"):
            continue
        out.append(r)
    return out


def spills(records: list[dict]) -> list[list[dict]]:
    """The records grouped by spill: each record with the one its duplicate_of names (followed to its end), so an EPA
    report paired with an EPD row, and an EPD row a corrected row replaced, count once."""
    ids = {r["event_id"]: r for r in records if r.get("event_id")}

    def root(r):
        seen = set()
        while r.get("duplicate_of") in ids and r["event_id"] not in seen:
            seen.add(r["event_id"])
            r = ids[r["duplicate_of"]]
        return r.get("event_id") or id(r)
    groups = defaultdict(list)
    for r in records:
        groups[root(r)].append(r)
    return list(groups.values())


def count_names(records: list[dict]) -> tuple[Counter, dict, dict]:
    """(spills per name key, {key: Counter of spellings}, {key: set of feeds}) over the records."""
    reports, spell, seen = Counter(), defaultdict(Counter), defaultdict(set)
    for group in spills(records):
        keys = set()
        for r in group:
            for n in split_names(r.get("waterbody_text")):
                k = key(n)
                spell[k][n] += 1
                seen[k].add(SEEN.get(r.get("source_id"), r.get("source_id")))
                keys.add(k)
        for k in keys:
            reports[k] += 1
    return reports, spell, seen


def spelling(c: Counter) -> str:
    """The spelling most records give; a tie goes to one not typed in capitals, then the first alphabetically."""
    return sorted(c.items(), key=lambda x: (-x[1], x[0].isupper(), x[0]))[0][0]


def kind_of(name: str) -> str:
    parts, _, trib = N.report_name_parts(name)
    return KINDS[2] if not parts else KINDS[1] if trib else KINDS[0]


def merge(meta: dict, rows: list[dict], reports: Counter, spell: dict, seen: dict) -> tuple[dict, list[dict], dict]:
    """(meta, rows, counts): the file's rows and resolved names kept with every field, their counts and feeds brought up
    to the whole history, and a row for each name neither holds."""
    have = {}
    for r in rows:
        have.setdefault(key(r["name"]), r)
    for r in meta.get("resolved") or []:
        have.setdefault(key(r["name"]), r)
    row_ids = {id(r) for r in rows}
    updated = 0
    for k, r in have.items():
        if k in reports:
            updated += r.get("reports") != reports[k]
            r["reports"] = reports[k]
            if id(r) in row_ids or "seen_in" in r:      # a resolved name keeps its own shape
                r["seen_in"] = sorted(set(r.get("seen_in") or []) | seen[k])
    new = []
    for k, n in reports.items():
        if k in have:
            continue
        name = spelling(spell[k])
        new.append({"name": name, "reports": n, "seen_in": sorted(seen[k]), "kind": kind_of(name)})
    rows = rows + new
    rows.sort(key=lambda r: (-r["reports"], r["name"]))
    return meta, rows, {"kept": len(have), "updated": updated, "new": len(new), "new_reports": sum(r["reports"] for r in new)}


def about(records: list[dict]) -> str:
    epd = [r for r in records if r["source_id"] == EPD]
    posts = sorted(p for r in epd for p in [(r.get("raw") or {}).get("_first_seen_posting"),
                                            (r.get("raw") or {}).get("posting_date")] if p)
    epa = [r for r in records if r["source_id"] == EPA]
    return ABOUT.format(first=posts[0] if posts else "?", last=posts[-1] if posts else "?", epd=f"{len(epd):,}",
                        epa=f"{len(epa):,}", paired=f"{sum(1 for r in epa if r.get('duplicate_of')):,}")


def build(events_dir: Path, out: Path, places: bool = True, resolver=None) -> dict:
    records = ga_records(events_dir)
    if not any(r["source_id"] == EPD for r in records):
        raise SystemExit(f"no {EPD} records in {events_dir}: run the Georgia feeds first (nothing written)")
    named = with_a_water(records, resolver)
    meta, rows = N.read_names_file(out) if out.exists() else ({}, [])
    before = {"names": len(rows), "reports": sum(r["reports"] for r in rows),
              "resolved_names": len(meta.get("resolved") or []),
              "resolved_reports": sum(r.get("reports", 0) for r in meta.get("resolved") or [])}
    reports, spell, seen = count_names(named)
    meta, rows, counts = merge(meta, rows, reports, spell, seen)
    meta["about"] = about(records)
    N.write_names_file(out, meta, "GA", rows, None, meta.get("build"))
    if places:
        N.add_places(out, "GA", events_dir)
    d = json.loads(out.read_text())
    after = {"names": d.get("waters"), "reports": d.get("reports"), "resolved_names": d.get("resolved_names", 0),
             "resolved_reports": d.get("resolved_reports", 0)}
    print(f"GA: {len(records)} records ({len(named)} naming a water), {len(spills(named))} spills, {len(reports)} names; rows {before['names']} "
          f"({before['reports']} reports) -> {after['names']} ({after['reports']}); resolved {before['resolved_names']} "
          f"-> {after['resolved_names']}; {counts['new']} new names ({counts['new_reports']} reports), "
          f"{counts['updated']} counts brought up to date -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return {"before": before, "after": after, **counts}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--events", type=Path, default=EVENTS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-places", action="store_true", help="skip the places pass (--add-places)")
    a = ap.parse_args(argv)
    build(a.events, a.out, places=not a.no_places)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
