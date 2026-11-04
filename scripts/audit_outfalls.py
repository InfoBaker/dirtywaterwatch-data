"""Outfall audit for the live states (docs/national-outfalls.md; owner, 2026-11-03: "make sure all of these new outlets
are in place for all covered states ... tied to water body and reflecting rain overflow concerns").

Per state: open combined sewer outfalls (official and provisional) with a point, with a water record, on the radar
(data/build/rainfall.json) or New Jersey's shared site (data/build/nj-cso-likely.json), and with a modeled reach
(data/build/reach-outfalls.json: traced, or tidal / lake at the outfall, where no river reach applies); treatment-plant
outfalls with a point and a water record; provisional places with a water record. Run before a state goes live and
after a registry change:  cd pipeline && .venv/bin/python -I ../scripts/audit_outfalls.py
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import live_states, load_outfall_registry  # noqa: E402
from build import status as S  # noqa: E402
from build.rain_likely import cso_open  # noqa: E402

REACH_DONE = {"traced", "tidal_at_outfall", "lake_at_outfall", "not_river"}


def read(p):
    try:
        return json.loads((ROOT / p).read_text())
    except (OSError, ValueError):
        return {}


def key(permit, outfall):
    return permit, str(outfall or "").lstrip("0") or "0"


def main() -> int:
    live = list(live_states())
    rain = read("data/build/rainfall.json")
    on_radar = {key(p, o.get("outfall")) for p, v in (rain.get("permits") or {}).items() for o in v.get("outfalls") or []}
    nj_site = {r.get("npdes_permit") for r in read("data/build/nj-cso-likely.json").get("permittees") or []}
    reach = {}
    for k, v in (read("data/build/reach-outfalls.json").get("outfalls") or {}).items():
        if isinstance(v, dict):
            reach[key(v.get("permit"), v.get("outfall"))] = v.get("status")
    rows = collections.defaultdict(collections.Counter)
    for o in load_outfall_registry():
        st = S.outfall_state(o)
        if st not in live or o.get("record_status") == "superseded":
            continue
        c, kind, pt, water = rows[st], o.get("outfall_kind"), o.get("lat") is not None, bool(o.get("water_slug"))
        if kind == "cso":
            if not cso_open(o):
                c["cso closed"] += 1
                continue
            k = key(o.get("npdes_permit"), o.get("outfall"))
            c["cso open"] += 1
            c["with point"] += pt
            c["with water"] += water
            c["rain"] += k in on_radar or (st == "NJ" and o.get("npdes_permit") in nj_site)
            c["reach done"] += reach.get(k) in REACH_DONE
            c["reach pending"] += reach.get(k) == "pending"
        elif kind == "plant":
            c["plant"] += 1
            c["plant water"] += water
        else:
            c["provisional"] += 1
            c["prov water"] += water
    cols = ["cso open", "with point", "with water", "rain", "reach done", "reach pending", "cso closed", "plant",
            "plant water", "provisional", "prov water"]
    print("state " + " ".join(h.rjust(13) for h in cols))
    tot = collections.Counter()
    for st in live:
        tot.update(rows[st])
        print(st.ljust(6) + " ".join(str(rows[st][h]).rjust(13) for h in cols))
    print("all   " + " ".join(str(tot[h]).rjust(13) for h in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
