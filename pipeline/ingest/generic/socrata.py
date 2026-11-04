"""Generic reader for Socrata open-data tables (not a feed; docs/generic-ingesters.md).

fetch block keys
  platform: socrata
  domain: https://opendata.<state>.gov;  dataset: the four-by-four id (stgj-u72u)
  format: json (the default: SODA /resource/<id>.json, $select of the safe fields only, paged by $limit and
          $offset in $order) or csv (one GET of /api/views/<id>/rows.csv?accessType=DOWNLOAD, the whole table;
          for hosts whose SODA endpoint refuses queries)
  where, order (":id" by default), page_size (1000), max_rows (200000)
  metadata: true asks /api/views/<id>.json; its rowsUpdatedAt becomes every record's source_updated_at
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ingest.generic.base import Fetched, get, get_json, load_pages, pages_doc
from ingest.generic.csv_json import read_csv


def urls(block: dict) -> dict:
    d, ds = block["domain"].rstrip("/"), block["dataset"]
    return {"json": f"{d}/resource/{ds}.json", "csv": f"{d}/api/views/{ds}/rows.csv?accessType=DOWNLOAD",
            "meta": f"{d}/api/views/{ds}.json"}


def fetch(block: dict, sess) -> Fetched:
    u = urls(block)
    if block.get("format") == "csv":
        r = get(sess, u["csv"], timeout=(15, 300))
        if "csv" not in (r.headers.get("content-type") or "") and "<html" in r.text[:500].lower():
            raise ValueError(f"not a CSV ({r.headers.get('content-type')}, {len(r.content)} bytes)")
        out = Fetched(r.content, "csv")
    else:
        size, cap = int(block.get("page_size", 1000)), int(block.get("max_rows", 200_000))
        params = {"$select": ",".join(f for f in block["safe_fields"] if "." not in f),
                  "$order": block.get("order", ":id"), "$limit": size}
        if block.get("where"):
            params["$where"] = block["where"]
        pages, n = [], 0
        while True:
            page = get_json(sess, u["json"], {**params, "$offset": n})
            if isinstance(page, dict) and page.get("error"):
                raise RuntimeError(f"Socrata error: {page.get('message') or page}")
            pages.append(page)
            n += len(page)
            if len(page) < size:
                break
            if n >= cap:
                raise RuntimeError(f"reached max_rows ({cap}) before the end of the table: raise max_rows")
        out = Fetched(pages_doc(pages, dataset=block["dataset"]), "json")
    if block.get("metadata"):
        r = get(sess, u["meta"], timeout=(15, 60))
        out.meta, out.meta_bytes = r.json(), r.content
    return out


def parse(block: dict, content: bytes) -> list[dict]:
    if block.get("format") == "csv":
        return read_csv(content.decode("utf-8-sig") if isinstance(content, bytes) else content, block)
    rows = []
    for page in load_pages(content):
        rows += [r for r in page if isinstance(r, dict)]
    return rows


def source_updated_at(block: dict, meta: dict | None, tz) -> str | None:
    """The table's own last-update time (rowsUpdatedAt, epoch seconds), in the block's zone."""
    upd = (meta or {}).get("rowsUpdatedAt")
    try:
        return datetime.fromtimestamp(int(upd), UTC).astimezone(tz).isoformat() if upd else None
    except (TypeError, ValueError, OverflowError):
        return None


def describe(block: dict) -> str:
    return json.dumps(urls(block))
