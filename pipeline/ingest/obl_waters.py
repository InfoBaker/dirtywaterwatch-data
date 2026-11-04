"""openboatlaunch's water records for one state -> data/waters-<st>.json (a registry helper, not a feed).

    python -m ingest.obl_waters --state XX --from <openboatlaunch>/out/water [--snapshot YYYY-MM-DD] [--out PATH]

openboatlaunch (the sibling project) is national: out/water/ holds one JSON file per water record per state
(<slug>.json, the slug ending in -<st>, with state, name, kind, towns, bbox, wikidata, charted, area_km2, launches
and advisories). This writes the state's records in the shape data/waters-{md,nj,ny,pa}.json carry (the generic
form of ingest/md_waters.py's extract, which now calls this one):

    {"state": "XX", "source": "openboatlaunch out/water snapshot <date>", "count": N, "waters": [...]}

each water {slug, name, kind, state, towns, bbox, wikidata, charted, area_km2, launches (launch slugs), advisories},
sorted by slug. Only files whose record says the state are taken (a water that crosses a state line has one record
per state there); a file that cannot be read (half-written in the snapshot) is skipped and counted. The snapshot date
comes from --snapshot, else the `built` (or `generated`, `updated`) date of out/meta.json beside out/water. Nothing is
fetched: it reads the snapshot on disk only (the project never fetches from openboatlaunch.org). Run it once per state
and per openboatlaunch snapshot, then scripts/gen_receiving_waters.py and the NHD state build (ingest.waters_from_nhd
--state XX) for the receiving waters openboatlaunch lacks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from common import DATA_DIR, write_json


def water_record(d: dict) -> dict:
    """One openboatlaunch out/water/<slug>.json -> the extract's shape."""
    return {
        "slug": d["slug"], "name": d.get("name"), "kind": d.get("kind"), "state": d.get("state"),
        "towns": list(d.get("towns") or []), "bbox": d.get("bbox"), "wikidata": d.get("wikidata"),
        "charted": d.get("charted"), "area_km2": d.get("area_km2"),
        "launches": [x["s"] for x in d.get("launches") or [] if isinstance(x, dict) and x.get("s")],
        "advisories": list(d.get("advisories") or []),
    }


def snapshot_of(obl_dir: Path) -> str | None:
    meta = Path(obl_dir).parent / "meta.json"
    try:
        m = json.loads(meta.read_text())
    except Exception:  # noqa: BLE001 - no meta.json: the date is unknown
        return None
    return str(m.get("built") or m.get("generated") or m.get("updated") or "")[:10] or None


def records(state: str, obl_dir: Path) -> tuple[list[dict], Counter]:
    """(the state's water records sorted by slug, counts of what was read and skipped)."""
    st = state.upper()
    seen = Counter()
    out = []
    for p in sorted(Path(obl_dir).glob(f"*-{st.lower()}.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:  # noqa: BLE001 - a half-written file in the snapshot is skipped, not fatal
            seen["unreadable"] += 1
            continue
        if not isinstance(d, dict) or str(d.get("state") or "").upper() != st or not d.get("slug"):
            seen["another state or no slug"] += 1
            continue
        out.append(water_record(d))
        seen["records"] += 1
    out.sort(key=lambda w: w["slug"])
    return out, seen


def extract(state: str, obl_dir: Path, out_json: Path | None = None, snapshot: str | None = None) -> dict:
    """Write data/waters-<st>.json (or out_json) and return what was written."""
    st = state.upper()
    if not re.fullmatch(r"[A-Z]{2}", st):
        raise ValueError(f"not a state code: {state!r}")
    obl_dir = Path(obl_dir)
    if not obl_dir.is_dir():
        raise FileNotFoundError(f"{obl_dir}: no openboatlaunch out/water directory here")
    waters, seen = records(st, obl_dir)
    snap = snapshot or snapshot_of(obl_dir)
    out = {"state": st, "source": f"openboatlaunch out/water snapshot {snap or 'unknown date'}",
           "count": len(waters), "waters": waters}
    write_json(Path(out_json) if out_json else DATA_DIR / f"waters-{st.lower()}.json", out)
    out["_read"] = dict(seen)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract openboatlaunch's water records for one state (not a feed)")
    ap.add_argument("--state", required=True, help="two-letter state code")
    ap.add_argument("--from", dest="obl_dir", required=True, help="openboatlaunch's out/water directory")
    ap.add_argument("--snapshot", help="snapshot date for the 'source' line (default: out/meta.json)")
    ap.add_argument("--out", help="output path (default data/waters-<st>.json)")
    args = ap.parse_args(argv)
    out = extract(args.state, Path(args.obl_dir), Path(args.out) if args.out else None, args.snapshot)
    kinds = Counter(w["kind"] for w in out["waters"])
    print(f"obl_waters: {out['count']} {out['state']} waters -> {args.out or f'data/waters-{out['state'].lower()}.json'} "
          f"({dict(kinds)}; read {out['_read']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
