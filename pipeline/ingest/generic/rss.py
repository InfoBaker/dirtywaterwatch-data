"""Generic reader for RSS 2.0 and Atom feeds: press releases, alerts, advisories (not a feed;
docs/generic-ingesters.md).

fetch block keys
  platform: rss
  url: the feed
Each item becomes a row with these fields (name the ones to keep in safe_fields; author fields are never
offered, they name people): id (guid, else Atom id, else link), title, link, published (pubDate, Atom
published, dc:date), updated (Atom updated), summary (description, Atom summary or content, HTML removed),
categories (joined with "; "). published is the publisher's time: map it to published_at, never to started_at
unless the item itself is the event's time.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from ingest.generic.base import Fetched, get

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
TAG_RE = re.compile(r"<[^>]+>")


def text_of(s: str | None) -> str | None:
    if s is None:
        return None
    t = html.unescape(TAG_RE.sub(" ", s))
    return " ".join(t.split()) or None


def _t(el, tag):
    x = el.find(tag)
    return x.text.strip() if x is not None and x.text else None


def items(xml: bytes | str) -> list[dict]:
    root = ET.fromstring(xml if isinstance(xml, bytes) else xml.encode())
    out = []
    if root.tag.endswith("rss") or root.find("channel") is not None:
        for it in root.iter("item"):
            link = _t(it, "link")
            out.append({"id": _t(it, "guid") or link, "title": text_of(_t(it, "title")), "link": link,
                        "published": _t(it, "pubDate") or _t(it, f"{DC}date"), "updated": None,
                        "summary": text_of(_t(it, "description") or _t(it, f"{CONTENT}encoded")),
                        "categories": "; ".join(c.text.strip() for c in it.findall("category") if c.text) or None})
    elif root.tag == f"{ATOM}feed":
        for it in root.iter(f"{ATOM}entry"):
            link = None
            for ln in it.findall(f"{ATOM}link"):
                if ln.get("rel") in (None, "alternate"):
                    link = ln.get("href")
                    break
            out.append({"id": _t(it, f"{ATOM}id") or link, "title": text_of(_t(it, f"{ATOM}title")), "link": link,
                        "published": _t(it, f"{ATOM}published"), "updated": _t(it, f"{ATOM}updated"),
                        "summary": text_of(_t(it, f"{ATOM}summary") or _t(it, f"{ATOM}content")),
                        "categories": "; ".join(c.get("term") for c in it.findall(f"{ATOM}category") if c.get("term"))
                        or None})
    else:
        raise ValueError(f"neither RSS nor Atom (root {root.tag})")
    return out


def fetch(block: dict, sess) -> Fetched:
    r = get(sess, block["url"], block.get("params"))
    items(r.content)            # fails here, before anything is written, when it is not a feed
    return Fetched(r.content, "xml")


def parse(block: dict, content: bytes) -> list[dict]:
    return items(content)
