"""Generic reader for plain CSV and JSON downloads (not a feed; docs/generic-ingesters.md).

fetch block keys
  platform: csv | json
  url: the download; params: query parameters
  csv: delimiter (","), encoding ("utf-8-sig"), skip_rows (lines before the header), headers: snake (the default:
       "FACILITY/COLLECTION_SYSTEM" -> facility_collection_system) or as_is
  json: records_path, the dotted path to the list of rows ("" = the document is the list; "features" with
       rows_from: properties for GeoJSON); paging: {param: offset, size_param: limit, size: 1000, max_rows}
       or {next: "links.next"} (a dotted path to the next page's URL)
"""
from __future__ import annotations

import csv
import io
import json
import re

from ingest.generic.base import Fetched, get, get_json, load_pages, pages_doc


def field_name(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower()).strip("_")


def read_csv(text: str, block: dict) -> list[dict]:
    opts = block.get("csv") or {}
    lines = text.lstrip("﻿")
    skip = int(opts.get("skip_rows") or 0)
    if skip:
        lines = "\n".join(lines.splitlines()[skip:])
    rd = csv.DictReader(io.StringIO(lines), delimiter=opts.get("delimiter", ","))
    snake = (opts.get("headers") or block.get("headers_style") or "snake") == "snake"
    out = []
    for r in rd:
        out.append({(field_name(k) if snake else k): (v if v is not None else "") for k, v in r.items() if k is not None})
    return out


def _dig(doc, path: str | None):
    if not path:
        return doc
    cur = doc
    for p in path.split("."):
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def rows_of_json(doc, block: dict) -> list[dict]:
    opts = block.get("json") or {}
    items = _dig(doc, opts.get("records_path"))
    if not isinstance(items, list):
        raise ValueError(f"no list at records_path {opts.get('records_path')!r}")
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if opts.get("rows_from") == "properties":      # GeoJSON: the properties, with the point's coordinates
            row = dict(it.get("properties") or {})
            g = it.get("geometry") or {}
            if g.get("type") == "Point" and isinstance(g.get("coordinates"), list):
                row["_x"], row["_y"] = g["coordinates"][:2]
            out.append(row)
        else:
            out.append(it)
    return out


def fetch(block: dict, sess) -> Fetched:
    if block["platform"] == "csv":
        r = get(sess, block["url"], block.get("params"))
        enc = (block.get("csv") or {}).get("encoding", "utf-8-sig")
        text = r.content.decode(enc)
        if "<html" in text[:500].lower():
            raise ValueError(f"an HTML page, not a CSV ({len(r.content)} bytes)")
        return Fetched(r.content, "csv")
    opts = block.get("json") or {}
    paging = opts.get("paging") or {}
    params = dict(block.get("params") or {})
    pages, n, url = [], 0, block["url"]
    while url:
        if paging.get("param"):
            params[paging["param"]] = n
            params[paging.get("size_param", "limit")] = int(paging.get("size", 1000))
        d = get_json(sess, url, params)
        pages.append(d)
        got = rows_of_json(d, block)
        n += len(got)
        if paging.get("next"):
            url, params = _dig(d, paging["next"]), {}
        elif paging.get("param") and len(got) >= int(paging.get("size", 1000)):
            pass
        else:
            url = None
        if not got or n >= int(paging.get("max_rows", 200_000)):
            break
    return Fetched(pages_doc(pages, url=block["url"]) if len(pages) > 1 else json.dumps(pages[0]).encode(), "json")


def parse(block: dict, content: bytes) -> list[dict]:
    if block["platform"] == "csv":
        enc = (block.get("csv") or {}).get("encoding", "utf-8-sig")
        return read_csv(content.decode(enc) if isinstance(content, bytes) else content, block)
    rows = []
    for page in load_pages(content):
        rows += rows_of_json(page, block)
    return rows
