"""A reviewed set of official notices: one page per notice, its records transcribed from the page by a reviewer and
checked against the page at every read (co_official_notices, mt_deq_notices).

Why
  Some states publish no feed: a large spill or an advisory reaches the public only in an agency's or an operator's
  news release, or in a line on a park's page. Such pages have no common structure, so a parser would guess. Here a
  reviewer reads the page once and writes each record's facts (dates, water, volume, the advice) beside the exact
  sentences of the page they rest on (`quotes`). Every run fetches the page and confirms each quote is still on it.

Notice kinds
  - "dated": a release about something that happened. Its records are rebuilt every run from the transcription while
    the page shows every quote; a page that no longer shows a quote keeps its records with raw.quotes_missing (the
    release changed: the reviewer re-reads it). Never confirmed by a later read: an advisory it announces ages out
    under the status build's rule unless the record gives an end.
  - "standing": a notice that stays on a page while it holds (a park's "red alert" line). Every read that shows its
    quotes confirms it (raw._last_seen_in_source); the first read that does not writes raw._unlisted_since at that read
    (a poll bound; the page gives no lift time), and the record keeps it.
  A page that cannot be fetched changes nothing: the previous records stay and the run's meta names the page. A notice
  never read successfully makes no record: the code claims only what it read.

Privacy
  The page itself is never saved (releases name staff and give their phones): data/raw/ gets, per page, the quotes
  found, the HTTP status and a hash of the page's text. Records carry only the transcribed facts.
"""
from __future__ import annotations

import hashlib
import html as H
import json
import re
import time
from typing import Callable

import requests

from common import HEADERS, event, save_raw

PAUSE_S = 1.0


def page_text(page: str) -> str:
    """The page's visible text, whitespace collapsed, typographic quotes and dashes made plain."""
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page)
    t = H.unescape(re.sub(r"<[^>]+>", " ", t))
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", t).strip()


def norm(s: str) -> str:
    return page_text(s).lower()


def check(text: str, quotes: list[str]) -> tuple[list[str], list[str]]:
    low = text.lower()
    found = [q for q in quotes if norm(q) in low]
    return found, [q for q in quotes if q not in found]


def fetch(url: str, timeout: int = 60) -> tuple[int | None, str | None, str | None]:
    """(status, text, error)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.RequestException as e:
        return None, None, f"{type(e).__name__}: {str(e)[:160]}"
    if r.status_code != 200:
        return r.status_code, None, f"HTTP {r.status_code}"
    return 200, page_text(r.text), None


def build(source_id: str, notices: list[dict], fetched: str, previous: list[dict],
          getter: Callable[[str], tuple[int | None, str | None, str | None]] = fetch,
          save: bool = True) -> tuple[list[dict], dict]:
    prev = {r["event_id"]: r for r in previous}
    out: dict[str, dict] = {}
    pages = []
    for i, n in enumerate(notices):
        if i and getter is fetch:
            time.sleep(PAUSE_S)
        status, text, err = getter(n["url"])
        quotes = [q for rec in n["records"] for q in rec.get("quotes") or []] + list(n.get("quotes") or [])
        quotes = list(dict.fromkeys(quotes))
        found, missing = check(text, quotes) if text is not None else ([], quotes)
        pages.append({"notice": n["id"], "url": n["url"], "http_status": status, "error": err,
                      "quotes_found": len(found), "quotes_missing": len(missing) if text is not None else None,
                      "text_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None})
        for rec in n["records"]:
            f = {k: v for k, v in rec.items() if k not in ("quotes", "raw")}
            raw = {**(rec.get("raw") or {}), "notice_id": n["id"], "notice_kind": n["kind"],
                   "quotes": rec.get("quotes") or [], "reviewed": n["reviewed"]}
            eid = f"{source_id}:{f['source_record_id']}"
            old = prev.get(eid)
            if text is None:                       # not read this run: the previous record stands, unchanged
                if old:
                    o = dict(old)
                    o["raw"] = {**(old.get("raw") or {}), "_last_fetch_error": err}
                    out[eid] = o
                continue
            mine_missing = [q for q in rec.get("quotes") or [] if q in missing]
            if n["kind"] == "standing":
                if not mine_missing:
                    raw["_last_seen_in_source"] = fetched
                else:
                    if not old:
                        continue                   # never seen on the page: no record
                    praw = old.get("raw") or {}
                    raw["_last_seen_in_source"] = praw.get("_last_seen_in_source")
                    raw["_unlisted_since"] = praw.get("_unlisted_since") or fetched
                    raw["ended_at_precision"] = "poll"
                    raw["end_basis"] = ("the first read of the page that no longer showed the notice (a poll bound; "
                                        "the page gives no lift time)")
            elif mine_missing:
                if not old:
                    continue                       # a release whose sentences are not on the page: nothing claimed
                raw["quotes_missing"] = mine_missing
            raw["_first_seen_at"] = ((old or {}).get("raw") or {}).get("_first_seen_at") or fetched
            out[eid] = event(source_id=source_id, fetched_at=fetched, source_url=n["url"],
                             published_at=n.get("published_at"), raw=raw, **f)
    for eid, old in prev.items():                  # records of a notice since removed from the set stay as they were
        out.setdefault(eid, old)
    if save:
        save_raw(source_id, json.dumps({"fetched_at": fetched, "pages": pages}, indent=1), "json")
    meta = {"registry_ids": [source_id], "pages": pages, "notices": len(notices),
            "pages_read": sum(1 for p in pages if p["http_status"] == 200)}
    return sorted(out.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True), meta
