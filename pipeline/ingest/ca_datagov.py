"""California Open Data Portal (data.ca.gov, CKAN) reading for the California feeds (shared helper, not a feed).

datastore_search with `fields` (only the safe fields are asked for), paged by offset; datastore_search_sql for a date
filter; package_show for a resource's last_modified, so a run whose table has not changed reads nothing more.
"""
from __future__ import annotations

import json

import requests

API = "https://data.ca.gov/api/3/action"
PAGE = 5000


def resource_modified(sess: requests.Session, package: str, resource_id: str) -> str | None:
    """The resource's last_modified (or the package's metadata_modified) as data.ca.gov gives it."""
    r = sess.get(f"{API}/package_show", params={"id": package}, timeout=(20, 60))
    r.raise_for_status()
    pkg = r.json()["result"]
    for res in pkg.get("resources") or []:
        if res.get("id") == resource_id:
            return res.get("last_modified") or pkg.get("metadata_modified")
    return pkg.get("metadata_modified")


def search(sess: requests.Session, resource_id: str, fields: list[str], max_rows: int = 200_000) -> list[dict]:
    """Every row of a datastore table, only `fields`."""
    out, offset = [], 0
    while True:
        r = sess.get(f"{API}/datastore_search", params={"resource_id": resource_id, "limit": PAGE, "offset": offset,
                                                        "fields": ",".join(fields), "sort": "_id asc"},
                     timeout=(20, 300))
        r.raise_for_status()
        res = r.json()["result"]
        rows = res.get("records") or []
        out += [{k: x.get(k) for k in fields} for x in rows]
        offset += len(rows)
        if not rows or offset >= (res.get("total") or 0):
            return out
        if offset >= max_rows:
            raise OverflowError(f"more than {max_rows} rows")


def sql(sess: requests.Session, resource_id: str, fields: list[str], where: str) -> list[dict]:
    """Rows matching a SQL condition, only `fields` (each quoted)."""
    cols = ", ".join(json.dumps(f) for f in fields)
    r = sess.get(f"{API}/datastore_search_sql",
                 params={"sql": f'SELECT {cols} FROM "{resource_id}" WHERE {where}'}, timeout=(20, 300))
    r.raise_for_status()
    return [{k: x.get(k) for k in fields} for x in r.json()["result"].get("records") or []]
