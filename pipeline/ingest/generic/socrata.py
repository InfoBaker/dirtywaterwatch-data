"""Generic reader for Socrata open-data tables (not a feed; docs/generic-ingesters.md).

fetch block keys
  platform: socrata
  domain: https://opendata.<state>.gov;  dataset: the four-by-four id (stgj-u72u)
  format: json (the default: SODA /resource/<id>.json, $select of the safe fields only, paged by $limit and
          $offset in $order) or csv (one GET of /api/views/<id>/rows.csv?accessType=DOWNLOAD, the whole table;
          for hosts whose SODA endpoint refuses queries)
  where, order (":id" by default), page_size (1000), max_rows (200000)
  metadata: true asks /api/views/<id>.json; its rowsUpdatedAt becomes every record's source_updated_at
  if_changed: true (with metadata: true) asks the metadata first and reads the table only when its rowsUpdatedAt differs
          from the last good run's (meta.table_version): a large table refreshed in batches is not paged through every
          hour. An unchanged table keeps the last good run's records, with meta.checked_at the time it was asked. The
          version is asked before and after paging: a read during which it moved is read again (three tries), and a
          read whose rows differ from the table's count(*) is refused, so a read torn by a refresh is never kept.
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
        guard = bool(block.get("if_changed"))
        for attempt in range(3 if guard else 1):
            before = current_version(block, sess) if guard else None
            pages, n = read_pages(block, sess, u)
            if not guard:
                break
            after = current_version(block, sess)
            if before == after:
                expected = row_count(block, sess, u)
                if expected is not None and expected != n:
                    raise RuntimeError(f"read {n} rows but the table counts {expected}: the read is not used")
                break
        else:
            raise RuntimeError("the table changed during each of 3 reads (rowsUpdatedAt moved): the read is not used")
        out = Fetched(pages_doc(pages, dataset=block["dataset"]), "json")
    if block.get("metadata"):
        r = get(sess, u["meta"], timeout=(15, 60))
        out.meta, out.meta_bytes = r.json(), r.content
    return out


def read_pages(block: dict, sess, u: dict) -> tuple[list, int]:
    """Every page of the safe fields, by $offset in $order: (pages, rows)."""
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
    return pages, n


def row_count(block: dict, sess, u: dict) -> int | None:
    """The table's own row count (count(*) under the block's where), None when it cannot be asked."""
    params = {"$select": "count(*) as n"}
    if block.get("where"):
        params["$where"] = block["where"]
    try:
        page = get_json(sess, u["json"], params)
        return int(page[0]["n"])
    except Exception:  # noqa: BLE001 - the version check stands alone
        return None


def table_version(block: dict, meta: dict | None) -> str | None:
    """The table's version for if_changed: its rowsUpdatedAt (epoch seconds) as text, None when absent."""
    upd = (meta or {}).get("rowsUpdatedAt")
    return str(upd) if upd not in (None, "") else None


def current_version(block: dict, sess) -> str | None:
    """The table's version now (one small metadata request), for if_changed."""
    r = get(sess, urls(block)["meta"], timeout=(15, 120))
    return table_version(block, r.json())


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
