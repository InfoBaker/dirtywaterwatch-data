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
end of a chain), deleted ones are counted. A record the extract on file holds is never dropped: when openboatlaunch
deleted it, moved it into another state, or no longer serves it, it stays as a tombstone (status deleted, moved or
not_in_snapshot, with successor_slug and retired_at), so the reports and outfall rows citing it keep their water
until a person retires it. The API's records carry no advisories: the extract on file keeps its own.

An extract on file built from another source (DC's, from NHD: ingest/dc_waters.py) is merged, never replaced
(merge_nhd): records matched by slug or numeric GNIS id take openboatlaunch's outline and fields, records only
openboatlaunch has are added, ours only we have are kept, and the source line says which is which. water_id (the
id shared by one water's records in several states: the Potomac's DC, MD and VA records) is recorded, not acted on. Only files whose record says the state are taken (a water that crosses a
state line has one record per state there, sharing water_id); a file that cannot be read is skipped and counted.
Keys an extract on file carries that this does not write (a hand field) are kept on the same slug. The snapshot date
comes from --snapshot, else the folder's out/meta.json (`built`, `generated` or `updated`), else the API's meta.
A result with fewer than half the records of the extract on file is refused (a partial snapshot never cuts it), and
so is an empty result, or a folder where the state's files are there but most do not decode (a damaged snapshot). Run
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

from common import DATA_DIR, gnis_num, write_json

LAUNCH_SHORT = {"s": "slug", "n": "name", "k": "kind", "st": "state", "t": "town", "x": "lon", "y": "lat", "f": "fee"}
API_FIELDS = ("water_id", "gnis_id", "geometry_hash", "geometry_tolerance_m", "status", "successor_slug",
              "previous_slugs", "updated_at")
BASE_FIELDS = ("slug", "name", "kind", "state", "towns", "bbox", "wikidata", "charted", "area_km2", "launches",
               "advisories")
WRITTEN = set(BASE_FIELDS) | set(API_FIELDS) | {"launches_unpublished", "slug_aliases"}
RETIRED = ("renamed", "merged")
TOMBSTONE = ("deleted", "moved", "not_in_snapshot")     # a record kept on file after openboatlaunch retired it


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
    if is_new_shape(d) and "advisories" not in d:
        # the API's records carry no advisories (2026-11-07): the extract on file keeps its own (merge_hand_fields)
        del out["advisories"]
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


def build_records(state: str, raw: list[dict], seen: Counter, lookup=None, gone: dict | None = None) -> list[dict]:
    """The extract's records from a state's raw records (either shape): active ones only, with slug_aliases. gone,
    when given, receives {slug: {status, successor_slug, retired_at}} for every record that is no longer a water of
    this state: "deleted", or "moved" (renamed or merged into a record outside this state's records, e.g.
    lake-superior-il into lake-superior-mn). write_extract keeps such a record as a tombstone when the extract on file
    holds it (its reports keep their water until a person moves them)."""
    st = state.upper()
    gone = {} if gone is None else gone
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
            gone[d["slug"]] = {"status": "deleted", "successor_slug": None, "retired_at": d.get("retired_at")}
    retired_at = {d["slug"]: d.get("retired_at") for d in raw if d.get("slug") in retired}
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
            gone[old] = {"status": "moved", "successor_slug": to or retired[old], "retired_at": retired_at.get(old)}
    for s, al in aliases.items():
        out[s]["slug_aliases"] = sorted(a for a in al if a not in out)
    seen["records"] += len(out)
    return [out[s] for s in sorted(out) if str(out[s].get("state") or st).upper() == st]


def records(state: str, obl_dir: Path, gone: dict | None = None) -> tuple[list[dict], Counter]:
    """(the state's water records from the folder, sorted by slug, counts of what was read and skipped)."""
    seen = Counter()
    obl_dir = Path(obl_dir)

    def lookup(slug):
        try:
            return json.loads((obl_dir / f"{slug}.json").read_text())
        except Exception:  # noqa: BLE001
            return None
    return build_records(state, folder_records(state, obl_dir, seen), seen, lookup, gone), seen


def api_records(state: str, gone: dict | None = None) -> tuple[list[dict], Counter, str]:
    """(the state's water records from the API's state list, counts, the snapshot date). Raises obl_api.ApiError."""
    import obl_api
    m = obl_api.meta()
    raw, snap = obl_api.state_waters(state, m.get("snapshot"))
    seen = Counter()
    raw = [d for d in raw if isinstance(d, dict) and d.get("slug")]
    built = str(m.get("built") or "")[:10] if snap == m.get("snapshot") else None
    return build_records(state, raw, seen, None, gone), seen, built or str(snap or "")[:8]


def merge_hand_fields(new: list[dict], path: Path) -> list[dict]:
    """Keep the keys the extract on file carries for a slug that this extract does not write (a hand field)."""
    try:
        have = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 - no extract on file
        have = {}
    old = {w.get("slug"): w for w in (have.get("waters") or []) if isinstance(w, dict)} if isinstance(have, dict) else {}
    out = []
    for w in new:
        o = old.get(w["slug"]) or {}
        if "advisories" not in w:
            w = {**w, "advisories": list(o.get("advisories") or [])}
        extra = {k: v for k, v in o.items() if k not in WRITTEN}
        out.append({**w, **extra} if extra else w)
    return out


def keep_tombstones(new: list[dict], path: Path, gone: dict, seen: Counter) -> list[dict]:
    """Never drop a record the extract on file holds: one that is now an alias of a record here (renamed or merged
    within the state) resolves through slug_aliases; any other (deleted, moved to another state, or no longer in the
    snapshot) stays as it is on file, marked status deleted, moved or not_in_snapshot with its successor and retired
    time, so the reports, outfall rows and aliases that cite it keep their water until a person retires it (review
    2026-11-07, P1-1)."""
    try:
        have = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 - no extract on file
        return new
    if not isinstance(have, dict) or not isinstance(have.get("waters"), list):
        return new
    slugs = {w["slug"] for w in new}
    aliased = {a for w in new for a in w.get("slug_aliases") or []}
    kept = []
    for o in have["waters"]:
        if not isinstance(o, dict) or not o.get("slug") or o["slug"] in slugs or o["slug"] in aliased:
            continue
        g = gone.get(o["slug"]) or {"status": "not_in_snapshot", "successor_slug": None, "retired_at": None}
        if o.get("status") in TOMBSTONE and o["slug"] not in gone:
            g = {k: o.get(k) for k in ("status", "successor_slug", "retired_at")}
        kept.append({**o, **g})
        seen[f"kept as {g['status']}"] += 1
    return sorted(new + kept, key=lambda w: w["slug"])


def on_file(path: Path) -> int:
    try:
        d = json.loads(Path(path).read_text())
        return len(d.get("waters") or []) if isinstance(d, dict) else 0
    except Exception:  # noqa: BLE001
        return 0


def nhd_built(st: str, path: Path) -> dict | None:
    """The extract on file when it is built from another source than openboatlaunch (DC's from NHD:
    ingest/dc_waters.py) and holds only this state's records: such a file is merged with openboatlaunch's records
    (merge_nhd), never replaced. None otherwise."""
    try:
        have = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(have, dict) or str(have.get("source") or "").startswith("openboatlaunch"):
        return None
    ws = have.get("waters")
    if not isinstance(ws, list) or not ws or any(str((w or {}).get("state") or "").upper() != st for w in ws):
        return None
    return have


MERGE_SIZE = ("area_km2", "length_km")


def merge_nhd(st: str, have: dict, waters: list[dict], raw_of, source: str, seen: Counter,
              gone: dict | None = None) -> dict:
    """The extract on file (built from NHD) merged with openboatlaunch's records of the state: a record of ours that
    is openboatlaunch's by slug or by GNIS id (compared as numbers: NHD's '00597915' is the API's 597915) takes its
    outline (inline, with its bbox and size), launches and the API fields (water_id, the shared id of the same water
    in other states, recorded and not acted on; geometry_hash, status, previous_slugs, updated_at ...); keeps its own
    slug, name, gnis_id text and other fields; an openboatlaunch slug that differs becomes a slug alias. A record
    openboatlaunch has and we lack is added (its outline inline). A record of ours openboatlaunch lacks is kept as it
    is. Each record says where it came from (record_from); the source line says which is which.

    A record an earlier merge added (record_from openboatlaunch, owned by openboatlaunch) follows openboatlaunch's
    lifecycle as an ordinary extract's does (SOL wave2 P2-9): renamed or merged into a record here, it is dropped and
    resolves through that record's slug_aliases; deleted, moved into another state, or no longer served, it stays as a
    tombstone (status deleted, moved or not_in_snapshot, with successor_slug and retired_at) so the reports citing it
    keep their water. Our own records (NHD's identities) are never retired here; they are matched through the incoming
    records' slug_aliases too, so a rename at openboatlaunch keeps them matched."""
    gone = gone or {}
    base = have.get("source_base") or have.get("source") or "the extract on file"
    by_slug = {w["slug"]: w for w in waters}
    by_alias = {}
    for w in waters:
        for x in w.get("slug_aliases") or []:
            if isinstance(x, str) and x not in by_slug:
                by_alias.setdefault(x, w["slug"])
    by_gnis = {}
    for w in waters:
        if gnis_num(w.get("gnis_id")):
            by_gnis.setdefault(gnis_num(w.get("gnis_id")), w["slug"])
    used, out, matched, own, retired = set(), [], [], [], []

    def outline(r: dict, a: dict) -> dict:
        raw = raw_of(a["slug"]) or {}
        if raw.get("geometry"):
            r["geometry"], r["bbox"], r["outline_from"] = raw["geometry"], a.get("bbox") or r.get("bbox"), "openboatlaunch"
            for k in MERGE_SIZE:
                if raw.get(k) is not None:
                    r[k] = raw[k]
        return r

    def incoming(slug):
        """openboatlaunch's record for a slug of ours: by slug, else the record it was renamed or merged into."""
        if not isinstance(slug, str):
            return None
        return by_slug.get(slug) or by_slug.get(by_alias.get(slug) or "")

    for o in have.get("waters") or []:
        if o.get("record_from") == "openboatlaunch":
            if o.get("slug") in by_slug:
                continue                # added by an earlier merge: added again below from openboatlaunch's record
            if o.get("slug") in by_alias:
                seen["dropped, now an alias"] += 1
                continue                # renamed or merged into a record here: resolves through its slug_aliases
            g = gone.get(o.get("slug")) or {"status": "not_in_snapshot", "successor_slug": None, "retired_at": None}
            if o.get("status") in TOMBSTONE and o.get("slug") not in gone:
                g = {k: o.get(k) for k in ("status", "successor_slug", "retired_at")}
            out.append({**o, **g})
            retired.append(o["slug"])
            seen[f"kept as {g['status']}"] += 1
            continue
        a = None
        for x in [o.get("slug")] + list(o.get("slug_aliases") or []):
            a = incoming(x)
            if a is not None:
                break
        a = a or by_slug.get(by_gnis.get(gnis_num(o.get("gnis_id"))) or "")
        if a is None or a["slug"] in used:
            out.append(o)
            if o.get("record_from") != "openboatlaunch":
                own.append(o["slug"])
            continue
        used.add(a["slug"])
        r = dict(o)
        for k in API_FIELDS:
            if k != "gnis_id":
                r[k] = a.get(k)
        if not r.get("gnis_id"):
            r["gnis_id"] = a.get("gnis_id")
        r["launches"], r["launches_unpublished"] = a.get("launches") or [], a.get("launches_unpublished") or []
        if a.get("towns") and not r.get("towns"):
            r["towns"] = a["towns"]
        al = list(r.get("slug_aliases") or [])
        for x in ([a["slug"]] if a["slug"] != r["slug"] else []) + list(a.get("slug_aliases") or []):
            if x not in al and x != r["slug"]:
                al.append(x)
        if al:
            r["slug_aliases"] = al
        r["record_from"] = "nhd+openboatlaunch"
        out.append(outline(r, a))
        matched.append(r["slug"])
        seen["matched"] += 1
    added = []
    have_slugs = {w.get("slug") for w in out}
    for a in waters:
        if a["slug"] in used or a["slug"] in have_slugs:
            continue
        r = outline({**a, "record_from": "openboatlaunch", "source": source}, a)
        if "advisories" not in r:
            r["advisories"] = []
        out.append(r)
        added.append(a["slug"])
        seen["added"] += 1
    seen["own"] = len(own)
    out.sort(key=lambda w: w["slug"])
    matched, added, retired = sorted(matched), sorted(added), sorted(retired)
    line = (f"{base}; merged with {source}: "
            f"{', '.join(matched) or 'none'} take openboatlaunch's outline and fields (matched by slug or GNIS id); "
            f"{', '.join(added) or 'none'} added from openboatlaunch; {len(own)} record(s) from the extract's own "
            "source only")
    merged = {"openboatlaunch": source, "matched": matched, "added": added, "own": sorted(own)}
    if retired:
        line += (f"; {', '.join(retired)} kept as retired by openboatlaunch (deleted, moved or no longer served), "
                 "their reports keeping their water")
        merged["retired"] = retired
    return {**{k: v for k, v in have.items() if k not in ("waters", "count")}, "state": st, "source": line,
            "source_base": base, "merged": merged, "count": len(out), "waters": out}


def write_extract(state: str, waters: list[dict], source: str, out_json: Path, seen: Counter,
                  gone: dict | None = None, raw_of=None) -> dict:
    st = state.upper()
    nhd = nhd_built(st, out_json)
    if nhd is not None:
        if not waters:
            # openboatlaunch has no record of the state: the extract on file is left exactly as it is
            out = dict(nhd)
            out["_read"] = dict(seen) | {"merged": 0}
            return out
        out = merge_nhd(st, nhd, waters, raw_of or (lambda slug: None), source, seen, gone)
        write_json(Path(out_json), out)
        out["_read"] = dict(seen)
        return out
    have = on_file(out_json)
    if not waters and not gone:
        # nothing decoded for the state: an empty extract is never written (SOL wave1 P2-11)
        raise Partial(f"no {st} record was read: an empty extract is never written, and "
                      f"{Path(out_json).name} is left as it is")
    # the records the source knows for the state: active ones, those retired into them, and those deleted or moved
    known = len(waters) + len(gone or {}) + sum(len(w.get("slug_aliases") or []) for w in waters)
    if known * 2 < have:
        raise Partial(f"{known} {st} records against {have} on file in {Path(out_json).name}: a partial "
                      "snapshot would cut the extract, which is left as it is")
    waters = keep_tombstones(merge_hand_fields(waters, out_json), out_json, gone or {}, seen)
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
            gone = {}
            waters, seen, snap = api_records(st, gone)
            seen["from"] = "api"
            src = f"openboatlaunch API v1 snapshot {snapshot or snap}"
            raw_of = None
            if waters and nhd_built(st, out_json) is not None:
                # a merge takes openboatlaunch's outlines: the state's list again, with them (a few records)
                full, _ = obl_api.state_waters(st, None, geometry=True)
                geo = {d.get("slug"): d for d in full if isinstance(d, dict)}
                raw_of = geo.get
            return write_extract(st, waters, src, out_json, seen, gone, raw_of)
        except obl_api.ApiError as ex:
            if obl_dir is None or not Path(obl_dir).is_dir():
                raise
            print(f"obl_waters: the API could not be read ({ex}); the folder is read instead", file=sys.stderr)
    if obl_dir is None or not Path(obl_dir).is_dir():
        raise FileNotFoundError(f"{obl_dir}: no openboatlaunch out/water directory here")
    obl_dir = Path(obl_dir)
    gone = {}
    waters, seen = records(st, obl_dir, gone)
    files = sum(1 for _ in obl_dir.glob(f"*-{st.lower()}.json"))
    bad = seen.get("unreadable", 0)
    if files and (bad == files or bad * 2 > files):
        # the files are there but (most of) their contents do not decode: a damaged snapshot, never a state with
        # fewer waters; the extract on file is left as it is (SOL wave1 P2-11)
        raise Partial(f"{bad} of the {files} {st} files in the openboatlaunch folder could not be read: a damaged "
                      f"snapshot would cut the extract, which is left as it is")
    snap = snapshot or snapshot_of(obl_dir)
    src = f"openboatlaunch out/water snapshot {snap or 'unknown date'}" + (f", changes to {until[:10]}" if until else "")

    def raw_of(slug):
        try:
            return json.loads((obl_dir / f"{slug}.json").read_text())
        except Exception:  # noqa: BLE001
            return None
    return write_extract(st, waters, src, out_json, seen, gone, raw_of)


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
