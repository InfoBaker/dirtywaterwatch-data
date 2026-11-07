"""research/hi/receiving-waters-missing.json: the water names Hawaii's reports give that
data/receiving-waters-national.json does not hold for HI, for the water batch (ingest.waters_from_nhd --names).

Usage: pipeline/.venv/bin/python -I scripts/hi_receiving_waters_missing.py [--events FILE] [--checked YYYY-MM-DD]

Reads the Department of Health's records as the feed wrote them (data/build/events/hi-doh-cwb-events-api.json, or
--events): each record's raw._water_names (the waters its notice names, read by ingest/hi_doh_cwb_events.py). A name
the national list holds for Hawaii is left out. Each row: the name, the number of records giving it, the islands and
the records per island, towns (the towns the records give, then the operators' towns, else the island's county seat,
with towns_basis saying which), permits, sources and the event types. The file is keyed by name, so a name two islands
share (Waimea Bay on Oahu and on Kauai) is one row with both islands: same_name_on_islands lists them for the batch,
which must build one record per island. Beaches and shores the Department names without a water (Kalapaki Beach Park,
North Shore) are counted in places_not_waters, not listed as rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest import hi_doh_cwb_events as HI  # noqa: E402

OUT = ROOT / "research" / "hi" / "receiving-waters-missing.json"
EVENTS = ROOT / "data" / "build" / "events" / f"{HI.SOURCE_ID}.json"
SEATS = {v[0]: v[1] for v in HI.ISLANDS.values()}


def national_keys() -> set[str]:
    d = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())
    rows = ((d.get("states") or {}).get("HI") or {}).get("waters") or []
    return {HI.key(n) for r in rows for n in [r.get("name"), *(r.get("names_seen") or [])] if n}


def build(records: list[dict], checked: str) -> dict:
    have = national_keys()
    dis = {r["id"]: r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "HI"}
    rows: dict[str, dict] = {}
    held, places = Counter(), 0
    for r in records:
        raw = r.get("raw") or {}
        names = raw.get("_water_names") or []
        if not names and raw.get("place_basis"):
            places += 1
        for n in names:
            if HI.key(n) in have:
                held[n] += 1
                continue
            o = rows.setdefault(n, {"name": n, "reports": 0, "islands": Counter(), "towns": defaultdict(Counter),
                                    "permits": set(), "event_types": Counter()})
            o["reports"] += 1
            isl = raw.get("island") or "unknown"
            o["islands"][isl] += 1
            if raw.get("town"):
                o["towns"][isl][raw["town"]] += 1
            op = dis.get(r.get("discharger_id") or "")
            if op:
                for t in op.get("towns") or []:
                    o["towns"][isl][t] += 0
            if r.get("npdes_permit"):
                o["permits"].add(r["npdes_permit"])
            o["event_types"][r["event_type"]] += 1
    out_rows = []
    for n, o in sorted(rows.items(), key=lambda kv: (-kv[1]["reports"], kv[0])):
        towns, basis = [], []
        for isl, _ in o["islands"].most_common():
            given = [t for t, c in o["towns"][isl].most_common() if c > 0]
            ops = [t for t, c in o["towns"][isl].most_common() if c == 0]
            if given:
                towns += given[:2]
                basis.append(f"{isl}: the towns the notices give")
            elif ops:
                towns += ops[:1]
                basis.append(f"{isl}: the operator's town")
            elif isl in SEATS:
                towns.append(SEATS[isl])
                basis.append(f"{isl}: the island's county seat (the notices name no town)")
        out_rows.append({"name": n, "reports": o["reports"], "islands": dict(o["islands"]),
                         "towns": list(dict.fromkeys(towns)), "towns_basis": "; ".join(basis),
                         "permits": sorted(o["permits"]), "sources": [HI.SOURCE_ID], "places_from": [HI.SOURCE_ID],
                         "event_types": dict(o["event_types"])})
    shared = [{"name": r["name"], "islands": r["islands"]} for r in out_rows if len(r["islands"]) > 1]
    return {
        "about": ("Water names in Hawaii's reports that data/receiving-waters-national.json does not hold for HI: the "
                  f"Department of Health Clean Water Branch's advisories (the newest 500 events, read on {checked}: sewage "
                  "spills, permit exceedances, Brown Water Advisories, beach advisories and retest notices), each name as "
                  "the notices give it with diacritics and the okina folded (the feed spells a water both ways: "
                  "Kane'ohe and Kaneohe), with the number of records giving it, the islands it is named on and the towns "
                  "near it. The notices give no coordinates. A name two islands share is one row here: build one record "
                  "per island (same_name_on_islands); the feed places a record only on a water of its own island."),
        "state": "HI", "checked": checked, "waters": len(out_rows), "reports": sum(r["reports"] for r in out_rows),
        "held_by_national_list": dict(held), "same_name_on_islands": shared,
        "places_not_waters": {"records": places, "note": ("records whose notice names a beach, park or shore and no "
                                                          "water (Kalapaki Beach Park, North Shore): kept with no water")},
        "rows": out_rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(EVENTS))
    ap.add_argument("--checked", default="2026-11-07")
    a = ap.parse_args(argv)
    records = json.loads(Path(a.events).read_text())["records"]
    doc = build(records, a.checked)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"HI: {doc['waters']} names, {doc['reports']} mentions; shared across islands: "
          f"{[s['name'] for s in doc['same_name_on_islands']]}; held by the national list: {doc['held_by_national_list']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
