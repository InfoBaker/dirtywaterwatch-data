"""Generic reader for ArcGIS REST layers, FeatureServer or MapServer (not a feed; docs/generic-ingesters.md).

fetch block keys
  platform: arcgis
  url: the layer (.../FeatureServer/0 or .../MapServer/0)
  where ("1=1"), out_fields (the safe fields by default: only those are asked for), order_by ("OBJECTID"),
  page_size (1000; paged by resultOffset while the server says exceededTransferLimit), max_rows (50000)
  geometry: true asks for points in WGS 84 (outSR 4326); each row then has _x and _y (map them to lon and lat)
  metadata: true asks the layer's description; its editingInfo.lastEditDate (epoch ms, UTC) becomes every
            record's source_updated_at
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ingest.generic.base import Fetched, get, get_json, load_pages, pages_doc


def fetch(block: dict, sess) -> Fetched:
    layer = block["url"].rstrip("/")
    fields = block.get("out_fields") or [f for f in block["safe_fields"] if not f.startswith("_")]
    size, cap = int(block.get("page_size", 1000)), int(block.get("max_rows", 50_000))
    pages, offset = [], 0
    while True:
        params = {"where": block.get("where", "1=1"), "outFields": ",".join(fields) if isinstance(fields, list) else fields,
                  "returnGeometry": "true" if block.get("geometry") else "false",
                  "orderByFields": block.get("order_by", "OBJECTID"), "resultOffset": offset,
                  "resultRecordCount": size, "f": "json"}
        if block.get("geometry"):
            params["outSR"] = 4326
        d = get_json(sess, f"{layer}/query", params, timeout=(15, 90))
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        pages.append(d)
        got = d.get("features") or []
        if not d.get("exceededTransferLimit") or not got or offset + len(got) >= cap:
            break
        offset += len(got)
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
