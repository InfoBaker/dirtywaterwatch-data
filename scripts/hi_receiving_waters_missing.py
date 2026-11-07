"""research/hi/receiving-waters-missing.json: the water names Hawaii's reports give that
data/receiving-waters-national.json does not hold for HI, for the water batch (ingest.waters_from_nhd --names).

Usage: pipeline/.venv/bin/python -I scripts/hi_receiving_waters_missing.py [--events FILE] [--checked YYYY-MM-DD]

Reads the Department of Health's records as the feed wrote them (data/build/events/hi-doh-cwb-events-api.json, or
--events): each record's raw._water_names (the waters its notice names, read by ingest/hi_doh_cwb_events.py). A name
the national list holds for Hawaii is left out. One row per name and island: the name, the island and place ("Waimea
Bay, Kauai") with a slug hint, the number of records, towns (the Census places nearest the water, by hand from its known
place, NEAR; else the towns the notices give), permits, sources and the event types. same_name_on_islands lists the
names on two islands: the batch must build one record per island. Beaches and shores the Department names without a water (Kalapaki Beach Park,
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
# (name, island) -> the Census places (2020 places and CDPs) nearest the water, by hand from the water's known place
# (review 2026-11-07 P2-5: the county seat is tens of kilometres off; the notices give no coordinates, so these are
# not geocoded from them)
NEAR = {
    ("Waimea Bay", "Oahu"): ["Pupukea", "Haleiwa"], ("Waimea Bay", "Kauai"): ["Waimea"],
    ("Kailua Bay", "Oahu"): ["Kailua"], ("Kailua Bay", "Hawaii"): ["Holualoa", "Kalaoa"],
    ("Pearl Harbor", "Oahu"): ["Pearl City", "Aiea"], ("East Loch", "Oahu"): ["Pearl City", "Aiea"],
    ("Kalauao Stream", "Oahu"): ["Aiea"], ("Kalauau Stream", "Oahu"): ["Aiea"],
    ("Sharks Cove", "Oahu"): ["Pupukea"], ("Kahana Bay", "Oahu"): ["Punaluu", "Kaaawa"],
    ("Kaneohe Bay", "Oahu"): ["Kaneohe"], ("Kawa Stream", "Oahu"): ["Kaneohe"],
    ("Ahuimanu Stream", "Oahu"): ["Ahuimanu"], ("Nuupia Pond", "Oahu"): ["Kailua", "Kaneohe"],
    ("Puha Stream", "Oahu"): ["Waimanalo"], ("Waimanalo Bay", "Oahu"): ["Waimanalo", "Waimanalo Beach"],
    ("Pokai Bay", "Oahu"): ["Waianae"], ("Yokohama Bay", "Oahu"): ["Makaha"], ("Lake Wilson", "Oahu"): ["Wahiawa"],
    **{(n, "Oahu"): ["Urban Honolulu"] for n in (
        "Ala Moana Lagoon", "Ala Wai Boat Harbor", "Ala Wai Canal", "Honolulu Harbor", "Keehi Lagoon", "Kalihi Stream",
        "Kamanaiki Stream", "Makiki Stream", "Manoa Stream", "Palolo Stream")},
    # Aina Haina and Hawaii Kai are in the 2020 Census place East Honolulu (the batch's Maunalua Bay record's town)
    **{(n, "Oahu"): ["East Honolulu"] for n in ("Wailupe Stream", "Maunalua Bay", "Kuapa Pond")},
    ("Wailua Bay", "Kauai"): ["Wailua", "Kapaa"], ("Hanalei Bay", "Kauai"): ["Hanalei", "Princeville"],
    ("Nawiliwili Bay", "Kauai"): ["Lihue"], ("Anahola Bay", "Kauai"): ["Anahola"],
    ("Kalihiwai Bay", "Kauai"): ["Kilauea"], ("Kukuiula Bay", "Kauai"): ["Poipu", "Koloa"],
    ("Keoniloa Bay", "Kauai"): ["Poipu", "Koloa"], ("Hanapepe Salt Pond", "Kauai"): ["Hanapepe"],
    ("Kahului Harbor", "Maui"): ["Kahului"], ("Kaopala Bay", "Maui"): ["Napili-Honokowai"],
    ("Maalaea Bay", "Maui"): ["Maalaea", "Kihei"], ("Maalaea Harbor", "Maui"): ["Maalaea"],
    ("Honolii Cove", "Hawaii"): ["Paukaa", "Hilo"], ("Puhi Bay", "Hawaii"): ["Hilo"],
    ("Wailoa River", "Hawaii"): ["Hilo"], ("Wailuku River", "Hawaii"): ["Hilo"],
    ("Honokohau Harbor", "Hawaii"): ["Kalaoa"], ("Kua Bay", "Hawaii"): ["Kalaoa"],
    ("Keokea Bay", "Hawaii"): ["Hawi"], ("Honaunau Bay", "Hawaii"): ["Honaunau-Napoopoo"],
    ("Kiilae Bay", "Hawaii"): ["Honaunau-Napoopoo"], ("Kahaluu Bay", "Hawaii"): ["Kahaluu-Keauhou"],
    ("Puako Bay", "Hawaii"): ["Puako"], ("Pauoa Bay", "Hawaii"): ["Puako"],
    ("Anaehoomalu Bay", "Hawaii"): ["Waikoloa Village"], ("Kawaihae Harbor", "Hawaii"): ["Kawaihae"],
}


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
            o = rows.setdefault((n, raw.get("island") or "unknown"),
                                {"name": n, "reports": 0, "islands": Counter(), "towns": defaultdict(Counter),
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
    for (n, isl), o in sorted(rows.items(), key=lambda kv: (-kv[1]["reports"], kv[0])):
        near = NEAR.get((n, isl))
        given = [t for t, c in o["towns"][isl].most_common() if c > 0]
        if near:
            towns, basis = near + [t for t in given if t not in near], "the nearest Census places, by hand from the water's known place"
        elif given:
            towns, basis = given[:2], "the towns the notices give"
        else:
            towns, basis = [SEATS.get(isl, "Honolulu")], "the island's county seat (no nearer place known)"
        out_rows.append({"name": n, "island": isl, "place": f"{n}, {isl}",
                         "slug_hint": f"{HI.key(n).replace(' ', '-')}-{isl.lower()}-hi", "reports": o["reports"],
                         "towns": towns, "towns_basis": basis, "permits": sorted(o["permits"]),
                         "sources": [HI.SOURCE_ID], "places_from": [HI.SOURCE_ID], "event_types": dict(o["event_types"])})
    names = Counter(r["name"] for r in out_rows)
    shared = [{"name": n, "islands": {r["island"]: r["reports"] for r in out_rows if r["name"] == n}}
              for n in sorted(names) if names[n] > 1]
    return {
        "about": ("Water names in Hawaii's reports that data/receiving-waters-national.json does not hold for HI: the "
                  f"Department of Health Clean Water Branch's advisories (the newest 500 events, read on {checked}: sewage "
                  "spills, permit exceedances, Brown Water Advisories, beach advisories and retest notices), each name as "
                  "the notices give it with diacritics and the okina folded (the feed spells a water both ways: "
                  "Kane'ohe and Kaneohe), with the number of records giving it, the islands it is named on and the towns "
                  "near it. The notices give no coordinates. A name two islands share has one row per island (island, place and "
                  "slug_hint say which): build one record each (same_name_on_islands); the feed places a record only on a "
                  "water of its own island. The towns are the Census places nearest each water, assigned by hand from "
                  "the water's known place (the notices give no coordinates)."),
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
