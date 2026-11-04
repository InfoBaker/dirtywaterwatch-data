"""Generic reader for ArcGIS REST layers, FeatureServer or MapServer (not a feed; docs/generic-ingesters.md).

fetch block keys
  platform: arcgis
  url: the layer (.../FeatureServer/0 or .../MapServer/0)
  where ("1=1"), out_fields (the safe fields by default: only those are asked for), cursor_field (the object id,
  "OBJECTID" by default: pages are "id greater than the last one seen", so a server that ignores resultOffset
  cannot repeat a page), page_size (1000), max_rows (50000; reaching it fails the fetch)
  geometry: true asks for points in WGS 84 (outSR 4326); each row then has _x and _y (map them to lon and lat)
  metadata: true asks the layer's description; its editingInfo.lastEditDate (epoch ms, UTC) becomes every
            record's source_updated_at
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ingest.generic.base import Fetched, get, get_json, load_pages, pages_doc


def fetch(block: dict, sess) -> Fetched:
    """Every feature, by a cursor on the object id (where <where> AND <id> > the last id seen, ordered by it): it
    works on servers that ignore resultOffset, and cannot repeat a page. A page whose ids do not move past the
    last one is an error; reaching max_rows is an error (a short table would mark every later row missing)."""
    layer = block["url"].rstrip("/")
    fields = list(block.get("out_fields") or [f for f in block["safe_fields"] if not f.startswith("_")])
    oid = block.get("cursor_field") or block.get("order_by") or "OBJECTID"
    if oid not in fields:
        fields.append(oid)
    size, cap = int(block.get("page_size", 1000)), int(block.get("max_rows", 50_000))
    base_where = block.get("where", "1=1")
    pages, last, n = [], None, 0
    for _ in range(cap // max(size, 1) + 2):
        where = base_where if last is None else f"({base_where}) AND {oid} > {last}"
        params = {"where": where, "outFields": ",".join(fields), "returnGeometry": "true" if block.get("geometry") else "false",
                  "orderByFields": f"{oid} ASC", "resultRecordCount": size, "f": "json"}
        if block.get("geometry"):
            params["outSR"] = 4326
        d = get_json(sess, f"{layer}/query", params, timeout=(15, 90))
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        got = d.get("features") or []
        if not got:
            break
        ids = [(f.get("attributes") or {}).get(oid) for f in got]
        if any(i is None for i in ids):
            raise RuntimeError(f"features without {oid}: the cursor cannot page this layer")
        if last is not None and min(ids) <= last:
            raise RuntimeError(f"the layer returned {oid} {min(ids)} again after {last}: paging is not moving")
        more = bool(d.get("exceededTransferLimit")) or len(got) >= size
        if more and any(x >= y for x, y in zip(ids, ids[1:])):
            # the server ignored orderByFields: the cursor (the page's largest id) would skip the ids below it
            raise RuntimeError(f"the layer returned a page out of {oid} order (orderByFields ignored): the cursor "
                               f"cannot page it")
        pages.append(d)
        n += len(got)
        last = max(ids)
        if n >= cap:
            raise RuntimeError(f"reached max_rows ({cap}) before the end of the layer: raise max_rows")
        if not d.get("exceededTransferLimit") and len(got) < size:
            break
    else:
        raise RuntimeError("the page limit was reached before the end of the layer")
    out = Fetched(pages_doc(pages, layer=layer), "json")
    if block.get("metadata"):
        r = get(sess, layer, {"f": "json"}, timeout=(15, 60))
        out.meta, out.meta_bytes = r.json(), r.content
    return out


def parse(block: dict, content: bytes) -> list[dict]:
    rows = []
    for page in load_pages(content):
        if "error" in page:
            raise RuntimeError(f"ArcGIS error in the saved response: {page['error']}")
        for f in page.get("features") or []:
            row = dict(f.get("attributes") or f.get("properties") or {})
            g = f.get("geometry") or {}
            if isinstance(g.get("x"), (int, float)) and isinstance(g.get("y"), (int, float)):
                row["_x"], row["_y"] = g["x"], g["y"]
            elif g.get("type") == "Point" and isinstance(g.get("coordinates"), list):
                row["_x"], row["_y"] = g["coordinates"][:2]
            rows.append(row)
    return rows


def source_updated_at(block: dict, meta: dict | None, tz) -> str | None:
    ms = ((meta or {}).get("editingInfo") or {}).get("lastEditDate")
    try:
        return datetime.fromtimestamp(int(ms) / 1000, UTC).astimezone(tz).isoformat() if ms else None
    except (TypeError, ValueError, OverflowError):
        return None


def describe(block: dict) -> str:
    return json.dumps({"layer": block["url"]})
