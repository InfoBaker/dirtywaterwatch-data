"""out/outfalls.json: every outfall of the registry in a live state, for the map's outfall layer and the Worker's live
layer (worker/src/live/api.ts reads it from R2 as current/outfalls.json). docs/national-outfalls.md is the spec.

Written by the export (export/build.py, `make export`) from the same rows as the operator and water pages; main()
rewrites it from the files on disk (scripts/export-outfalls.py, run by scripts/upload-current.sh before the upload).

Rows: the registry (common.load_outfall_registry: every data/outfalls-*.json, national) in the live states
(build/status.py states(): the one list the state pages, placement and the export use; a state going live brings
its outfalls with it), every outfall with coordinates or a water record, with or without a water record:

  {source_id, npdes_permit, outfall_id, outfall_kind ("cso" | "plant"), outfall_status (as EPA lists it; CLS is
   closed), discharger_id (the operator page, by permit), permittee, state, lat, lon, receiving_water (as the
   permit names it), water_slugs ([] when there is no water record yet), water_match (how the registry matched
   the water: geometry+name, geometry, name_only, none), rain}

`rain` is null or the operator's "discharge likely" row of out/rain.json: {status ("likely" | "suppressed" |
"below" | "no_reading"), rain_24h_in, threshold_in, threshold_kind, trigger_basis ("operator" | "state" | "default"),
valid_time, episode}; only on open combined
sewer outfalls (closed, plant and "reported" outfalls never drive the caution).

Provisional places from the overflow reports (data/build/outfalls-reported.json, docs/national-outfalls.md: kind
"reported", or "cso" for a combined sewer outfall the reports place) also carry record_status ("provisional" |
"confirmed"), confidence ("high" | "medium" | "low"), report_count, last_report_at, event_ids, reached_water
("yes" | "no" | "unknown") and on_map; a row without record_status is an official listing. The site draws them apart
and labels them "Provisional location from overflow reports"; npdes_permit is null for an operator with no permit on
file. A place whose reports all say the sewage reached no water (on_map false) is left out here (the operator page
lists it). discharger_id is null when the row's operator has no page. A plant row placed at the facility's point
because EPA lists no outfall coordinates carries coords_from "facility" (its outfall_id is "").

Then the MassDEP layer's ids (data/build/ma-cso-outfalls.json, e.g. SPR010) as rows of their own, source_id
"ma-massdep", so the live layer can place a MassDEP report by the id it carries; such a row has `alias_of`
("<permit>:<outfall>") when the registry holds the same outfall, and the map draws the registry row instead.

Last the monthly marks (out/monthly-outfalls.json, docs/plan.md §2.x): an outfall whose latest report is a monthly
total gets status "monthly", days, events, month, received_at, label and event_id; a mark for an outfall the
registry lacks becomes a row of its own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common import (BUILD_DIR, DATA_DIR, OUT_DIR, PROVISIONAL_FIELDS, discharger_alias_map, is_provisional, outfall_key,
                    read_json)

COORD_DIGITS = 5                    # about 1 m, as the export's other files
MARK_FIELDS = ("status", "days", "events", "month", "received_at", "label", "event_id")
RAIN_FIELDS = ("status", "rain_24h_in", "threshold_in", "threshold_kind", "trigger_basis", "valid_time", "episode")
SOURCE_BY_KIND = {"cso": "echo", "plant": "epa-icis-npdes"}   # a row without its own source_id


def closed(o: dict) -> bool:
    return str(o.get("outfall_status") or "").upper().startswith("CLS")


def receiving_water(o: dict) -> str | None:
    """The receiving water as the permit names it (a reviewed correction of EPA's name first). None for a provisional
    place: its text is quoted from the reports (it can name a property owner) and has not been through the export's
    redaction; its water record (water_slugs) stands instead."""
    if is_provisional(o):
        return None
    ov = o.get("receiving_water_override")
    if isinstance(ov, dict) and ov.get("water"):
        return ov["water"]
    return o.get("receiving_water_echo") or o.get("receiving_water") or None


def coord(v):
    try:
        return round(float(v), COORD_DIGITS) if v is not None else None
    except (TypeError, ValueError):
        return None


def permit_index(dischargers: list[dict]) -> dict[str, str]:
    """{permit: operator id} from the operator registry rows: a row's own permit first, then its other permits."""
    out: dict[str, str] = {}
    for field in ("npdes_permit", "npdes_permits"):
        for d in dischargers:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            v = d.get(field)
            for p in (v if isinstance(v, list) else [v]):
                if p:
                    out.setdefault(str(p).strip().upper(), d["id"])
    return out


def rain_of(permit_row: dict | None) -> dict | None:
    if not isinstance(permit_row, dict):
        return None
    from build.rain_likely import basis_of          # a rain.json written before the basis was carried: worked out
    return {**{k: permit_row.get(k) for k in RAIN_FIELDS}, "trigger_basis": basis_of(permit_row)}


def outfall_rows(registry: list[dict], live: set[str], *, waters: set[str] | None = None, canon=None,
                 dischargers: list[dict] | None = None, rain_permits: dict | None = None, ma_layer=None,
                 marks: list[dict] | None = None) -> list[dict]:
    """The rows of out/outfalls.json (module docstring). registry: common.load_outfall_registry() rows; live: the
    live states; waters: the slugs of the water records (a slug that is no record is left out); canon: an older
    slug -> its record (status.SLUG_ALIASES); rain_permits: the rain block's "permits"; ma_layer: the MassDEP
    layer's outfalls ({dep_id: row} or a list); marks: out/monthly-outfalls.json "outfalls"."""
    canon = canon or (lambda s: s)
    dischargers = dischargers or []
    by_permit = permit_index(dischargers)
    aliases = discharger_alias_map(dischargers)
    ids = {d["id"] for d in dischargers if isinstance(d, dict) and d.get("id")}

    def operator(permit: str, did) -> str | None:
        """The operator page: by permit, else the row's own id when it is one of the registry's (or an alias)."""
        did = aliases.get(did, did) if isinstance(did, str) else None
        return by_permit.get(permit) or (did if did in ids else None)
    rain_permits = rain_permits or {}
    rows, by_key = [], {}
    for o in registry:
        permit = str(o.get("npdes_permit") or "").strip().upper()
        st = str(o.get("state") or permit[:2]).upper()
        prov = is_provisional(o)
        if (not permit and not (prov and o.get("discharger_id"))) or st not in live:
            continue
        if o.get("outfall_kind") == "other":
            continue                    # not a sewage outfall (kind_note): no point on the map
        if prov and o.get("on_map") is False:
            continue                    # its reports all say the sewage reached no water: the operator page lists it
        slug = canon(o["water_slug"]) if o.get("water_slug") else None
        slugs = [slug] if slug and (waters is None or slug in waters) else []
        lat, lon = coord(o.get("lat")), coord(o.get("lon"))
        if (lat is None or lon is None) and not slugs:
            continue                    # nothing to draw and nothing to place by
        kind = o.get("outfall_kind") or "cso"
        did = o.get("discharger_id")
        row = {"source_id": o.get("source_id") or SOURCE_BY_KIND.get(kind, "echo"), "npdes_permit": permit or None,
               "outfall_id": str(o.get("outfall") if o.get("outfall") is not None else ""), "outfall_kind": kind,
               "outfall_status": o.get("outfall_status"),
               "discharger_id": operator(permit, did),
               "permittee": o.get("permittee"), "state": st, "lat": lat, "lon": lon,
               "receiving_water": receiving_water(o), "water_slugs": slugs, "water_match": o.get("match"),
               "rain": rain_of(rain_permits.get(permit)) if kind == "cso" and permit and not closed(o)
               and o.get("rain_caution") is not False else None}     # a lake reversal gate: not rain-driven
        if prov:                        # a place from the overflow reports: provisional, drawn apart on the map
            row.update({k: o.get(k) for k in PROVISIONAL_FIELDS})
        if o.get("coords_from") == "facility":
            row["coords_from"] = "facility"     # the plant's own point stands in: no outfall coordinates on file
        if o.get("country") and o["country"] != "US":
            row["country"] = o["country"]
        rows.append(row)
        if permit and row["outfall_id"]:
            by_key.setdefault(outfall_key(permit, row["outfall_id"]), row)
    if "MA" in live:
        layer = (ma_layer.values() if isinstance(ma_layer, dict) else ma_layer) or []
        for dep_id, m in ((m.get("dep_id"), m) for m in layer if isinstance(m, dict)):
            permit = str(m.get("npdes") or "").strip().upper()
            if not dep_id or not permit:
                continue
            hit = by_key.get(outfall_key(permit, m.get("outfall")))
            lat, lon = coord(m.get("lat")), coord(m.get("lon"))
            rows.append({"source_id": "ma-massdep", "npdes_permit": permit, "outfall_id": str(dep_id),
                         "outfall_kind": (hit or {}).get("outfall_kind", "cso"),
                         "outfall_status": (hit or {}).get("outfall_status"), "discharger_id": by_permit.get(permit),
                         "permittee": (hit or {}).get("permittee") or m.get("system"), "state": "MA", "lat": lat,
                         "lon": lon, "receiving_water": (hit or {}).get("receiving_water") or m.get("receiving_water"),
                         "water_slugs": list((hit or {}).get("water_slugs") or []),
                         "water_match": (hit or {}).get("water_match"), "rain": (hit or {}).get("rain"),
                         "alias_of": f"{permit}:{hit['outfall_id']}" if hit else None})
    for m in marks or []:
        if not isinstance(m, dict) or not m.get("npdes_permit") or not m.get("outfall_id"):
            continue
        permit = str(m["npdes_permit"]).strip().upper()
        if permit[:2] not in live:
            continue
        key = outfall_key(permit, m["outfall_id"])
        row = by_key.get(key)
        if row is None:                 # a monthly report for an outfall the registry lacks (CSO monthly reports)
            did = m.get("discharger_id")
            row = {"source_id": m.get("source_id"), "npdes_permit": permit, "outfall_id": str(m["outfall_id"]),
                   "outfall_kind": "cso", "outfall_status": None,
                   "discharger_id": operator(permit, did),
                   "permittee": m.get("discharger_name"), "state": permit[:2], "lat": coord(m.get("lat")),
                   "lon": coord(m.get("lon")), "receiving_water": None,
                   "water_slugs": [canon(s) for s in m.get("water_slugs") or [] if waters is None or canon(s) in waters],
                   "water_match": None, "rain": None}
            rows.append(row)
            by_key[key] = row
        row.update({k: m.get(k) for k in MARK_FIELDS})
    return rows


def summary(rows: list[dict]) -> str:
    from collections import Counter
    by = Counter((r["state"], r["outfall_kind"]) for r in rows if not r.get("alias_of"))
    return (f"outfalls.json: {len(rows)} rows ({sum(1 for r in rows if r.get('alias_of'))} state-layer ids), "
            f"{sum(1 for r in rows if r['water_slugs'])} with a water record, "
            f"{sum(1 for r in rows if r.get('status') == 'monthly')} monthly marks, "
            f"{sum(1 for r in rows if (r.get('rain') or {}).get('status') == 'likely')} with the rain caution; "
            + ", ".join(f"{s} {k} {n}" for (s, k), n in sorted(by.items())))


def write(rows: list[dict], out_dir: Path = OUT_DIR, built: str | None = None) -> Path:
    """out/outfalls.json, compact."""
    p = Path(out_dir) / "outfalls.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"built": built, "generated_from": "the outfall registry (EPA's combined sewer outfall inventory and state "
           "layers) in the states this site covers, with the monthly marks and the rain caution", "count": len(rows),
           "outfalls": rows}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(p)
    return p


def ma_layer_rows(build_dir: Path = BUILD_DIR):
    doc = read_json(Path(build_dir) / "ma-cso-outfalls.json", {}) or {}
    return doc.get("outfalls") if isinstance(doc, dict) and "outfalls" in doc else doc


def main(out_dir: Path = OUT_DIR, data_dir: Path = DATA_DIR, build_dir: Path = BUILD_DIR) -> list[dict]:
    """Rewrite out/outfalls.json from the files on disk: the registry and water records (data/), the operator
    registry, out/rain.json and out/monthly-outfalls.json (written by the export)."""
    from build import status as status_mod
    from common import load_outfall_registry, now_iso
    from export.build import load_dischargers

    waters = status_mod.load_waters()
    rain = read_json(Path(out_dir) / "rain.json", {}) or {}
    try:
        marks = (read_json(Path(out_dir) / "monthly-outfalls.json", {}) or {}).get("outfalls") or []
    except (OSError, ValueError, AttributeError):
        marks = []
    dis, _ = load_dischargers()
    rows = outfall_rows(load_outfall_registry(data_dir), status_mod.states(), waters=set(waters),
                        canon=lambda s: status_mod.SLUG_ALIASES.get(s, s), dischargers=dis,
                        rain_permits=rain.get("permits") or {}, ma_layer=ma_layer_rows(build_dir), marks=marks)
    write(rows, out_dir, now_iso())
    print(summary(rows))
    return rows


if __name__ == "__main__":
    sys.exit(0 if main() is not None else 1)
