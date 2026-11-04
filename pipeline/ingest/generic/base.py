"""Shared pieces of the platform readers (not a feed): the HTTP session, the fetched response, and a JSON page
request that fails loudly. Each platform module has fetch(block, sess) -> Fetched and parse(block, content) -> rows."""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from common import BROWSER_HEADERS, HEADERS

TIMEOUT = (15, 120)


@dataclass
class Fetched:
    content: bytes                  # what was fetched, as saved to data/raw/<source>/ (pages joined as one JSON)
    ext: str                        # json, csv, xml, html
    meta: dict | None = None        # the platform's metadata for the dataset or layer, when asked for
    meta_bytes: bytes | None = None


def session(block: dict) -> requests.Session:
    """The pipeline's session: its own user agent, or a browser's where the host answers only that
    (browser_headers: true in the block)."""
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS if block.get("browser_headers") else HEADERS)
    s.headers.update(block.get("headers") or {})
    return s


def get(sess: requests.Session, url: str, params: dict | None = None, timeout=TIMEOUT) -> requests.Response:
    r = sess.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def get_json(sess: requests.Session, url: str, params: dict | None = None, timeout=TIMEOUT):
    r = get(sess, url, params, timeout)
    try:
        return r.json()
    except ValueError as e:
        raise ValueError(f"not JSON from {url} ({r.headers.get('content-type')}, {len(r.content)} bytes)") from e


def pages_doc(pages: list, **head) -> bytes:
    return json.dumps({**head, "pages": pages}, ensure_ascii=False).encode()


def load_pages(content: bytes | str) -> list:
    """The pages of a saved response: {"pages": [...]} as the runner saves it, or one page as the server gave it."""
    d = json.loads(content.decode("utf-8-sig") if isinstance(content, bytes) else content)
    if isinstance(d, dict) and isinstance(d.get("pages"), list):
        return d["pages"]
    return [d]
