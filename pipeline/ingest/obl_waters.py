"""openboatlaunch's water records for one state -> data/waters-<st>.json (a registry helper, not a feed).

    python -m ingest.obl_waters --state XX --from <openboatlaunch>/out/water [--snapshot YYYY-MM-DD] [--out PATH]
    python -m ingest.obl_waters --state XX --from-api [--from <out/water>] [--out PATH]

openboatlaunch (the sibling project) is national: one JSON record per water per state (<slug>.json, the slug ending in
-<st>). It reaches the pipeline two ways: the folder out/water (the national bulk file of its API, or the R2 copy,
unpacked into ../openboatlaunch/out by scripts/state_paths.py fetch-obl / unpack-obl), or the API's state list
(--from-api: states/{ST}/waters, 500 a page, outlines left out; key in OBL_API_KEY, never printed; pipeline/obl_api.py).
With --from-api and --from both, the folder is the fallback when the API cannot be read (said in the output).

This writes the state's records in the shape data/waters-{md,nj,ny,pa}.json carry:

    {"state": "XX", "source": "openboatlaunch out/water snapshot <date>", "count": N, "waters": [...]}

each water {slug, name, kind, state, towns, bbox, wikidata, charted, area_km2, launches (published launch slugs),
advisories}, sorted by slug, and, from the API's record shape (schema 1, 2026-11-07), also water_id, gnis_id,
geometry_hash, geometry_tolerance_m, status, successor_slug, previous_slugs, updated_at, launches_unpublished (the
slugs of the private, commercial and club launches the API serves as points with visibility "unpublished": kept here
with their visibility, and the export decides; it shows published launches only) and slug_aliases (the slugs
openboatlaunch renamed or merged into this record: its previous_slugs and every renamed or merged record whose
successor it is; build/status.py slug_aliases resolves them, so events, outfall rows and pages follow the new slug).
A record of the older shape (the R2 copy packed by hand: short launch keys s n k st t x y f a) gives exactly the
fields it gave before.

Only active records are water records: renamed and merged ones become slug_aliases of their successor (followed to the
end of a chain), deleted ones are counted. Only files whose record says the state are taken (a water that crosses a
state line has one record per state there, sharing water_id); a file that cannot be read is skipped and counted.
Keys an extract on file carries that this does not write (a hand field) are kept on the same slug. The snapshot date
comes from --snapshot, else the folder's out/meta.json (`built`, `generated` or `updated`), else the API's meta.
A result with fewer than half the records of the extract on file is refused (a partial snapshot never cuts it). Run
it per state on a state build; the hourly changes check (ingest.obl_changes) rewrites the live states' extracts
from the folder when openboatlaunch changes them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from common import DATA_DIR, write_json

LAUNCH_SHORT = {"s": "slug", "n": "name", "k": "kind", "st": "state", "t": "town", "x": "lon", "y": "lat", "f": "fee"}
API_FIELDS = ("water_id", "gnis_id", "geometry_hash", "geometry_tolerance_m", "status", "successor_slug",
              "previous_slugs", "updated_at")
BASE_FIELDS = ("slug", "name", "kind", "state", "towns", "bbox", "wikidata", "charted", "area_km2", "launches",
               "advisories")
WRITTEN = set(BASE_FIELDS) | set(API_FIELDS) | {"launches_unpublished", "slug_aliases"}
RETIRED = ("renamed", "merged")


class Partial(Exception):
    """The records found would cut the extract on file (a partial snapshot or answer)."""


def launch(x: dict) -> dict | None:
    """One launch of a water record, in the long keys (slug, name, kind, state, town, lon, lat, fee, access,
    visibility, url), from either shape: the API's long keys, or the older short keys (published only; `a` 'r' is
    restricted access). None when it has no slug."""
    if not isinstance(x, dict):
        return None
    if x.get("slug"):
        return {k: x.get(k) for k in ("slug", "name", "kind", "state", "town", "lon", "lat", "fee", "access",
                                      "visibility", "url")} | {"visibility": x.get("visibility") or "published"}
    if x.get("s"):
        o = {v: x.get(k) for k, v in LAUNCH_SHORT.items()}
        o.update(access="public_restricted" if x.get("a") == "r" else "public", visibility="published", url=None)
        return o
    return None


def launches(d: dict) -> list[dict]:
    return [o for o in (launch(x) for x in d.get("launches") or []) if o]


def is_new_shape(d: dict) -> bool:
    return "status" in d or "water_id" in d


def water_record(d: dict) -> dict:
    """One openboatlaunch water record (either shape) -> the extract's shape."""
    ls = launches(d)
    out = {
        "slug": d["slug"], "name": d.get("name"), "kind": d.get("kind"), "state": d.get("state"),
        "towns": list(d.get("towns") or []), "bbox": d.get("bbox"), "wikidata": d.get("wikidata"),
        "charted": d.get("charted"), "area_km2": d.get("area_km2"),
        "launches": [x["slug"] for x in ls if x["visibility"] == "published"],
        "advisories": list(d.get("advisories") or []),
    }
    if is_new_shape(d):
        for k in API_FIELDS:
            out[k] = list(d.get(k) or []) if k == "previous_slugs" else d.get(k)
        out["launches_unpublished"] = [x["slug"] for x in ls if x["visibility"] != "published"]
    return out


def snapshot_of(obl_dir: Path) -> str | None:
    meta = Path(obl_dir).parent / "meta.json"
    try:
        m = json.loads(meta.read_text())
    except Exception:  # noqa: BLE001 - no meta.json: the date is unknown
        return None
    return str(m.get("built") or m.get("generated") or m.get("updated") or "")[:10] or None


def folder_records(state: str, obl_dir: Path, seen: Counter) -> list[dict]:
    """The raw records of the state in the folder (files *-<st>.json whose record says the state)."""
    st = state.upper()
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
        out.append(d)
    return out


def successor_of(slug: str, retired: dict[str, str], lookup=None, limit: int = 20) -> str | None:
    """The active record a renamed or merged slug ends at, following a chain (retired: {slug: successor} known;
    lookup(slug) -> raw record or None for a successor outside them). None for a loop or a dead end."""
    seen = {slug}
    cur = retired.get(slug)
    for _ in range(limit):
        if cur is None or cur in seen:
            return None
        if cur in retired:
            seen.add(cur)
            cur = retired[cur]
            continue
        if lookup is not None:
            d = lookup(cur)
            if isinstance(d, dict) and d.get("status") in RETIRED and d.get("successor_slug"):
                seen.add(cur)
                cur = d["successor_slug"]
                continue
            if isinstance(d, dict) and d.get("status") == "deleted":
                return None
        return cur
    return None


def build_records(state: str, raw: list[dict], seen: Counter, lookup=None) -> list[dict]:
    """The extract's records from a state's raw records (either shape): active ones only, with slug_aliases."""
    st = state.upper()
    active, retired = {}, {}
    for d in raw:
        status = d.get("status") or "active"
        if status == "active":
            active[d["slug"]] = d
        elif status in RETIRED and d.get("successor_slug"):
            retired[d["slug"]] = d["successor_slug"]
            seen[status] += 1
        else:
            seen[status if status in ("deleted",) + RETIRED else "other status"] += 1
    out = {s: water_record(d) for s, d in active.items()}
    aliases: dict[str, set] = {}
    for s, d in active.items():
        for old in d.get("previous_slugs") or []:
            if isinstance(old, str) and old and old != s:
                aliases.setdefault(s, set()).add(old)
    for old in retired:
        to = successor_of(old, retired, lookup)
        if to in out:
            aliases.setdefault(to, set()).add(old)
        else:
            seen["retired, successor not in this state's records"] += 1
    for s, al in aliases.items():
        out[s]["slug_aliases"] = sorted(a for a in al if a not in out)
    seen["records"] += len(out)
    return [out[s] for s in sorted(out) if str(out[s].get("state") or st).upper() == st]


def records(state: str, obl_dir: Path) -> tuple[list[dict], Counter]:
    """(the state's water records from the folder, sorted by slug, counts of what was read and skipped)."""
    seen = Counter()
    obl_dir = Path(obl_dir)

    def lookup(slug):
        try:
            return json.loads((obl_dir / f"{slug}.json").read_text())
        except Exception:  # noqa: BLE001
            return None
    return build_records(state, folder_records(state, obl_dir, seen), seen, lookup), seen


def api_records(state: str) -> tuple[list[dict], Counter, str]:
    """(the state's water records from the API's state list, counts, the snapshot date). Raises obl_api.ApiError."""
    import obl_api
    m = obl_api.meta()
    raw, snap = obl_api.state_waters(state, m.get("snapshot"))
    seen = Counter()
    raw = [d for d in raw if isinstance(d, dict) and d.get("slug")]
    built = str(m.get("built") or "")[:10] if snap == m.get("snapshot") else None
    return build_records(state, raw, seen), seen, built or str(snap or "")[:8]


def merge_hand_fields(new: list[dict], path: Path) -> list[dict]:
    """Keep the keys the extract on file carries for a slug that this extract does not write (a hand field)."""
    try:
        have = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 - no extract on file
        return new
    old = {w.get("slug"): w for w in (have.get("waters") or []) if isinstance(w, dict)} if isinstance(have, dict) else {}
    out = []
    for w in new:
        o = old.get(w["slug"]) or {}
        extra = {k: v for k, v in o.items() if k not in WRITTEN}
        out.append({**w, **extra} if extra else w)
    return out


def on_file(path: Path) -> int:
    try:
        d = json.loads(Path(path).read_text())
        return len(d.get("waters") or []) if isinstance(d, dict) else 0
    except Exception:  # noqa: BLE001
        return 0


def write_extract(state: str, waters: list[dict], source: str, out_json: Path, seen: Counter) -> dict:
    st = state.upper()
    have = on_file(out_json)
    if len(waters) * 2 < have:
        raise Partial(f"{len(waters)} {st} records against {have} on file in {Path(out_json).name}: a partial "
                      "snapshot would cut the extract, which is left as it is")
    waters = merge_hand_fields(waters, out_json)
    out = {"state": st, "source": source, "count": len(waters), "waters": waters}
    write_json(Path(out_json), out)
    out["_read"] = dict(seen)
    return out


def extract(state: str, obl_dir: Path | None, out_json: Path | None = None, snapshot: str | None = None,
            from_api: bool = False, until: str | None = None) -> dict:
    """Write data/waters-<st>.json (or out_json) and return what was written. from_api: the API's state list, with
    obl_dir (when given) the fallback on an API failure; until: the changes check's time the folder is current to,
    named in the source line. Raises Partial, FileNotFoundError, and obl_api.ApiError when the API was asked and
    there is no folder to fall back on."""
    st = state.upper()
    if not re.fullmatch(r"[A-Z]{2}", st):
        raise ValueError(f"not a state code: {state!r}")
    out_json = Path(out_json) if out_json else DATA_DIR / f"waters-{st.lower()}.json"
    if from_api:
        import obl_api
        try:
            waters, seen, snap = api_records(st)
            seen["from"] = "api"
            src = f"openboatlaunch API v1 snapshot {snapshot or snap}"
            return write_extract(st, waters, src, out_json, seen)
        except obl_api.ApiError as ex:
            if obl_dir is None or not Path(obl_dir).is_dir():
                raise
            print(f"obl_waters: the API could not be read ({ex}); the folder is read instead", file=sys.stderr)
    if obl_dir is None or not Path(obl_dir).is_dir():
        raise FileNotFoundError(f"{obl_dir}: no openboatlaunch out/water directory here")
    obl_dir = Path(obl_dir)
    waters, seen = records(st, obl_dir)
    snap = snapshot or snapshot_of(obl_dir)
    src = f"openboatlaunch out/water snapshot {snap or 'unknown date'}" + (f", changes to {until[:10]}" if until else "")
    return write_extract(st, waters, src, out_json, seen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract openboatlaunch's water records for one state (not a feed)")
    ap.add_argument("--state", required=True, help="two-letter state code")
    ap.add_argument("--from", dest="obl_dir", help="openboatlaunch's out/water directory (with --from-api: the fallback)")
    ap.add_argument("--from-api", action="store_true", help="read the state from the openboatlaunch API (OBL_API_KEY)")
    ap.add_argument("--snapshot", help="snapshot date for the 'source' line (default: out/meta.json or the API's meta)")
    ap.add_argument("--out", help="output path (default data/waters-<st>.json)")
    args = ap.parse_args(argv)
    if not args.obl_dir and not args.from_api:
        ap.error("give --from DIR or --from-api")
    try:
        out = extract(args.state, Path(args.obl_dir) if args.obl_dir else None, Path(args.out) if args.out else None,
                      args.snapshot, from_api=args.from_api)
    except Partial as ex:
        print(f"obl_waters: refused: {ex}", file=sys.stderr)
        return 1
    except Exception as ex:  # noqa: BLE001 - the API's errors carry no key (obl_api.scrub)
        if type(ex).__name__ != "ApiError":
            raise
        print(f"obl_waters: the API could not be read and no folder was given ({ex})", file=sys.stderr)
        return 1
    kinds = Counter(w["kind"] for w in out["waters"])
    print(f"obl_waters: {out['count']} {out['state']} waters -> {args.out or f'data/waters-{out['state'].lower()}.json'} "
          f"({dict(kinds)}; read {out['_read']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
