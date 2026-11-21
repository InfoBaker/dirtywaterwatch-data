"""Shared reading for Ohio's Great Lakes CSO notices posted as one PDF per notice (40 CFR 122.38): the index page's
links, each PDF's text, and the state that keeps every notice read. Each city's own form is read by its module
(oh_fremont_cso, oh_avon_lake_cso), which supplies the link pattern, the parser and the record. Not a feed by itself:
it has no __main__.

How a run goes (run_feed)
  - The index page is read; the notice links are the PDF links the city module's pattern selects. No link at all is a
    failed read (the page changed, or an error page): ok=False, the previous records kept, the state unchanged.
  - Each listed PDF not yet read is fetched once and read with pypdf (layout text, as la_baton_rouge_quarterly does).
    The PDFs carry staff names, telephones and e-mail addresses: the PDF and its text are never saved; only the
    fields the city module parses are kept (state and raw save). A PDF already read is not fetched again; one that
    failed is tried again on the next run.
  - A PDF whose text is not the city's form (the parser raises NoticeError), or that cannot be fetched, is unread:
    the readable notices are saved and published, the unread ones are named in the error, and health stays false
    (partial) until they read. A PDF with no text layer at all (a scanned image) is unread the same way ("no text
    layer") and is tried again each run: a notice we cannot read holds health false (review 2026-11-16).
  - Every wall-clock time the city modules read must exist in America/New_York (existing): a time in the
    spring-forward gap is not read.
  - A notice that leaves the index stays in the state: a past report. One that leaves it before it could be read is
    moved from the unread list to state.left_unread (it can no longer be read, so it no longer holds health false).
"""
from __future__ import annotations

import io
import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import requests

from common import HEADERS, read_json, save_raw, write_events, write_json
from common import error_detail, error_text


class NoticeError(ValueError):
    """A notice PDF whose text is not the form the city module reads."""


class LayoutError(ValueError):
    """The index page lists no notice: a failed read, never "no overflows"."""


def existing(dt):
    """dt when its wall-clock time exists in its zone, else None: a time in the spring-forward gap (02:30 on the
    second Sunday of March) is no instant, so it is never published as one (review 2026-11-16)."""
    from datetime import UTC
    if dt is None:
        return None
    back = dt.astimezone(UTC).astimezone(dt.tzinfo)
    return dt if back.replace(tzinfo=None) == dt.replace(tzinfo=None) else None


def pdf_text(content: bytes) -> str:
    import pypdf                    # pipeline/requirements.txt; imported here so the parsers run without it
    return "\n".join((p.extract_text(extraction_mode="layout") or "") for p in pypdf.PdfReader(io.BytesIO(content)).pages)


def index_links(page: str, base: str, pattern: re.Pattern) -> list[str]:
    """The absolute addresses of the page's PDF links whose address matches pattern, in page order, once each."""
    out = []
    for href in re.findall(r'href="([^"]+\.pdf)"', page, re.I):
        url = urljoin(base, unescape(href))
        if pattern.search(url) and url not in out:
            out.append(url)
    return out


def lines(text: str) -> list[str]:
    return [" ".join(x.split()) for x in text.splitlines() if x.strip()]


def merge(state: dict, url: str, parsed: dict | None, now: str, image_only: bool = False) -> None:
    held = state.setdefault("notices", {})
    prev = held.get(url) or {}
    held[url] = {**(parsed or {}), "url": url, "image_only": image_only,
                 "first_seen_at": prev.get("first_seen_at") or now, "last_seen_at": now}
    state.setdefault("unread", {}).pop(url, None)


def run_feed(source_id: str, index_url: str, pattern: re.Pattern, parse: Callable[[str], dict],
             to_records: Callable[[list[dict]], list[dict]], state_path: Path, now: str,
             get: Callable[[str], requests.Response] | None = None, out: Path | None = None,
             credit: str = "", text_of: Callable | None = None,
             extra_meta: Callable[[dict], dict] | None = None) -> int:
    """One run of a PDF-notice feed (module docstring). Returns the exit code."""
    get = get or (lambda u: requests.get(u, headers=HEADERS, timeout=(20, 90)))
    try:
        r = get(index_url)
        r.raise_for_status()
        links = index_links(r.text, index_url, pattern)
        if not links:
            raise LayoutError("no notice PDF link on the index page")
    except (requests.RequestException, LayoutError) as e:
        write_events(source_id, [], ok=False, error=f"index: {error_text(e)}", path=out)
        print(f"{source_id}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    state = read_json(state_path, {}) or {}
    held = state.setdefault("notices", {})
    unread = state.setdefault("unread", {})
    for url in [u for u in unread if u not in links]:      # taken off the index before it could be read
        state.setdefault("left_unread", {})[url] = {"why": unread.pop(url), "seen_gone_at": now}
    new = []
    for url in links:
        if url in held:
            held[url]["last_seen_at"] = now
            continue
        try:
            resp = get(url)
            resp.raise_for_status()
            text = text_of(resp) if text_of else pdf_text(resp.content)
            if not lines(text):
                # a scanned notice: there is a notice we cannot read, so it stays unread (health false) and is
                # tried again each run (review 2026-11-16 P1)
                unread[url] = "no text layer (a scanned image)"
                continue
            parsed = parse(text)
        except (requests.RequestException, NoticeError, ValueError, ImportError) as e:
            unread[url] = f"{error_text(e)}"      # pypdf missing: unread, never "no notices"
            continue
        merge(state, url, parsed, now)
        new.append(parsed)
    state["last_read"] = {"at": now, "listed": len(links), "new": len(new), "unread": len(unread)}
    write_json(state_path, state)
    if new:
        save_raw(source_id, json.dumps(new), "json")            # the parsed fields only, never the PDFs
    recs = to_records([n for n in held.values() if not n.get("image_only")])
    meta = {"registry_ids": [source_id], "url": index_url, "listed": len(links), "notices_held": len(held),
            "image_only": sorted(u for u, n in held.items() if n.get("image_only")), "credit": credit,
            "left_unread": sorted(state.get("left_unread") or {}),
            **(extra_meta(held) if extra_meta else {})}
    if unread:
        meta["unread"] = unread
        write_events(source_id, recs, ok=False, partial=True, meta=meta, path=out,
                     error="notices not read: " + "; ".join(f"{u.rsplit('/', 1)[-1]}: {why}" for u, why in unread.items()))
        print(f"{source_id}: PARTIAL {len(recs)} records; {len(unread)} notices not read", file=sys.stderr)
        return 1
    write_events(source_id, recs, meta=meta, path=out)
    print(f"{source_id}: {len(recs)} records from {len(held)} notices")
    return 0


class FileGet:
    """For --file runs and tests: the index page and the PDFs' extracted text from saved files (no network)."""

    def __init__(self, index_url: str, index_html: str, texts: dict[str, str]):
        self.index_url, self.index_html, self.texts = index_url, index_html, texts

    def __call__(self, url: str):
        return _Resp(self.index_html if url == self.index_url else None, self.texts.get(url), url)


def file_text(resp) -> str:
    """text_of for FileGet: the saved text in place of a PDF."""
    return resp._pdf or ""


class _Resp:
    def __init__(self, text, pdf_text_, url):
        self.text, self._pdf, self.url = text or "", pdf_text_, url
        self.content = b""

    def raise_for_status(self):
        if self.text == "" and self._pdf is None:
            raise requests.HTTPError(f"404 for {self.url}")
